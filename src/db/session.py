"""Database engine and tenant-scoped query helpers.

This module intentionally supports **sync SQLAlchemy sessions** (Phase 1 repo default)
while providing an **async engine/sessionmaker** for future async-first paths.

Pool guidance:
- **SQLite (dev/tests)**: no real pooling; configure ``check_same_thread=False`` and
  prefer file-based SQLite for multi-connection tests.
- **Postgres (prod)**: enable ``pool_pre_ping`` and a bounded pool. Recommended
  defaults are conservative and should be tuned with load testing.

Security:
- Never log raw connection strings (they may embed credentials).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any, TypeVar

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from config import get_settings

from .base import Base

T = TypeVar("T")


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def reset_engine() -> None:
    global _engine, _SessionLocal, _async_engine, _AsyncSessionLocal
    # Tests frequently monkeypatch DATABASE_URL; ensure Settings cache doesn't pin the old URL.
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if _async_engine is not None:
        _async_engine.sync_engine.dispose()
    _async_engine = None
    _AsyncSessionLocal = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            _engine = create_engine(
                url,
                future=True,
                connect_args=connect_args,
                poolclass=NullPool,
            )
        else:
            _engine = create_engine(
                url,
                future=True,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                connect_args=connect_args,
            )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SessionLocal


def get_async_engine() -> AsyncEngine:
    """Create an AsyncEngine when DATABASE_URL uses an async dialect (e.g. asyncpg)."""
    global _async_engine
    if _async_engine is None:
        url = get_settings().database_url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            # For async sqlite, callers should provide sqlite+aiosqlite. Keep pool disabled.
            _async_engine = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)
        else:
            _async_engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                connect_args=connect_args,
            )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


def init_db() -> None:
    # Ensure ORM models are imported so they register tables on Base.metadata.
    import db.models  # noqa: F401
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


def tenant_scoped_query(
    session: Session,
    model: type[T],
    *,
    tenant_id: str,
    trading_mode: str,
    tenant_column: str = "tenant_id",
    mode_column: str = "trading_mode",
) -> Any:
    """Build a SELECT filtered by ``tenant_id`` and ``trading_mode`` (paper/live isolation)."""
    tid = getattr(model, tenant_column)
    mode = getattr(model, mode_column)
    return select(model).where(tid == tenant_id, mode == trading_mode)


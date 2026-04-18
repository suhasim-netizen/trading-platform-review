"""Test-wide environment and shared fixtures — must run before ``config.get_settings`` is first evaluated."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    os.environ.setdefault("SECRET_KEY", "a" * 32)
    os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("ALLOWED_TENANT_IDS", "tenant_a,tenant_b,director")
    # config.Settings validates broker OAuth/app settings for non-development.
    # Provide deterministic dummy values so scaffolding tests can run in production mode.
    os.environ.setdefault("BROKER_CLIENT_ID", "dummy-client-id")
    os.environ.setdefault("BROKER_CLIENT_SECRET", "dummy-client-secret")
    os.environ.setdefault("BROKER_REDIRECT_URI", "https://localhost/callback")
    os.environ.setdefault("BROKER_AUTH_BASE_URL", "https://localhost/auth")
    os.environ.setdefault("BROKER_API_BASE_URL", "https://localhost/api/v3")
    os.environ.setdefault("MARKET_DATA_BASE_URL", "https://api.tradestation.com")
    os.environ.setdefault("BROKER_WS_BASE_URL", "wss://localhost/ws")
    # Unit tests use non-sim broker URL mocks unless PAPER_TRADING_MODE is enforced per test.
    os.environ.setdefault("PAPER_TRADING_MODE", "false")
    # Multi-account routing defaults for unit tests.
    os.environ.setdefault("TS_EQUITY_ACCOUNT_ID", "EQ-DEFAULT")
    os.environ.setdefault("TS_OPTIONS_ACCOUNT_ID", "OPT-DEFAULT")
    os.environ.setdefault("TS_FUTURES_ACCOUNT_ID", "FUT-DEFAULT")


@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """Isolated SQLite file + fresh engine per test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ALLOWED_TENANT_IDS", "tenant_a,tenant_b")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TS_EQUITY_ACCOUNT_ID", "EQ-TEST")
    monkeypatch.setenv("TS_OPTIONS_ACCOUNT_ID", "OPT-TEST")
    monkeypatch.setenv("TS_FUTURES_ACCOUNT_ID", "FUT-TEST")

    from config import get_settings

    get_settings.cache_clear()

    from db.session import reset_engine

    reset_engine()

    from api.main import create_app

    return create_app()


@pytest.fixture
def make_test_app(monkeypatch):
    """Create an app with custom ENVIRONMENT/ALLOWED_TENANT_IDS."""

    def _make(*, environment: str = "development", allowed: str = "tenant_a,tenant_b"):
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("ALLOWED_TENANT_IDS", allowed)

        from config import get_settings

        get_settings.cache_clear()

        from api.main import create_app

        return create_app()

    return _make

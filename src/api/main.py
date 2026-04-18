"""FastAPI app factory for the client dashboard API (Phase 1 scaffolding).

Tenant context is injected by :class:`src.tenancy.middleware.TenantContextMiddleware`.
Routers must never infer tenant_id from query/body; they should only read it from
``src.tenancy.context`` after middleware has validated request headers.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Match pytest.ini ``pythonpath = src`` so ``uvicorn src.api.main:app`` from repo root resolves
# top-level packages (``tenancy``, ``config``, …) under ``src/``.
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI

from tenancy.middleware import TenantContextMiddleware
from tenancy.context import get_tenant_id, get_trading_mode
from tenancy.rate_limit import FixedWindowTenantRateLimiter
from tenancy.rate_limit_middleware import TenantRateLimitMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Task 3 scaffolding: no DB init here yet.
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Trading Platform Dashboard API", lifespan=_lifespan)
    # Draft: in-memory per-tenant rate limiting (default permissive).
    app.add_middleware(TenantRateLimitMiddleware, limiter=FixedWindowTenantRateLimiter(limit=10_000, window_s=60))
    app.add_middleware(TenantContextMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/tenant")
    def tenant_info() -> dict[str, str]:
        # Tenant context is guaranteed by TenantContextMiddleware for this route.
        return {"tenant_id": get_tenant_id(), "trading_mode": get_trading_mode().value}

    return app


# Uvicorn entrypoint (smoke tests / local dev).
app = create_app()



"""Tenant context middleware (header-based).

Phase 1 Task 3 requirement:
- Read ``X-Tenant-ID`` (and optionally ``X-Trading-Mode``) from each request.
- Validate tenant_id against ``Settings.ALLOWED_TENANT_IDS`` when running in production.
- Store the validated values in request-scoped context for downstream code.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import get_settings
from .context import TradingMode, clear_tenant_context, set_tenant_context


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Sets request context based on headers (no JWT parsing in this layer)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        tenant_id = (request.headers.get("X-Tenant-ID") or "").strip()
        if not tenant_id:
            return JSONResponse({"detail": "missing X-Tenant-ID header"}, status_code=401)

        mode_raw = (request.headers.get("X-Trading-Mode") or "paper").strip().lower()
        try:
            mode = TradingMode(mode_raw)
        except ValueError:
            return JSONResponse({"detail": "invalid trading_mode"}, status_code=400)

        settings = get_settings()
        if settings.environment == "production":
            allowed = settings.allowed_tenants()
            if tenant_id not in allowed:
                return JSONResponse({"detail": "tenant not permitted"}, status_code=403)

        if getattr(settings, "environment", "development") != "production":
            # In non-production, we still require the header, but we don't enforce allowlisting.
            pass

        set_tenant_context(tenant_id=str(tenant_id), trading_mode=mode)
        try:
            return await call_next(request)
        finally:
            clear_tenant_context()


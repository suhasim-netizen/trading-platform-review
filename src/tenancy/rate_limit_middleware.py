# DRAFT — Pending Security Architect sign-off (P1-03)

"""Rate limit middleware keyed by X-Tenant-ID (draft)."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .rate_limit import FixedWindowTenantRateLimiter


class TenantRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant rate limiting using request header `X-Tenant-ID`."""

    def __init__(self, app, limiter: FixedWindowTenantRateLimiter) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        tenant_id = (request.headers.get("X-Tenant-ID") or "").strip()
        if not self._limiter.allow(tenant_id):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)


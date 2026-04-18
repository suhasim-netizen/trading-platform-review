# DRAFT — Pending Security Architect sign-off (P1-03)

from __future__ import annotations

from fastapi.testclient import TestClient


def test_rate_limit_keyed_by_tenant_id(test_app):
    # Build an app with a strict limiter (2 requests per window).
    from api.main import create_app
    from tenancy.rate_limit import FixedWindowTenantRateLimiter
    from tenancy.rate_limit_middleware import TenantRateLimitMiddleware
    from tenancy.middleware import TenantContextMiddleware

    app = create_app()
    app.user_middleware.clear()
    app.add_middleware(TenantRateLimitMiddleware, limiter=FixedWindowTenantRateLimiter(limit=2, window_s=60))
    app.add_middleware(TenantContextMiddleware)

    with TestClient(app) as client:
        # Tenant A hits limit.
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_a"}).status_code == 200
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_a"}).status_code == 200
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_a"}).status_code == 429

        # Tenant B has its own bucket.
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_b"}).status_code == 200
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_b"}).status_code == 200
        assert client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_b"}).status_code == 429


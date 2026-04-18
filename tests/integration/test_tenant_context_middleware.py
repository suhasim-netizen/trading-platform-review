from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_bypass_does_not_require_tenant_header(test_app):
    with TestClient(test_app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_tenant_context_required_and_returned(make_test_app):
    app = make_test_app(environment="development", allowed="tenant_a,tenant_b")
    with TestClient(app) as client:
        r = client.get("/v1/tenant")
        assert r.status_code == 401

        r = client.get("/v1/tenant", headers={"X-Tenant-ID": "tenant_a", "X-Trading-Mode": "paper"})
        assert r.status_code == 200
        assert r.json() == {"tenant_id": "tenant_a", "trading_mode": "paper"}


def test_production_tenant_allowlist_enforced(make_test_app):
    app = make_test_app(environment="production", allowed="tenant_a,tenant_b")
    with TestClient(app) as client:
        r = client.get(
            "/v1/tenant",
            headers={"X-Tenant-ID": "tenant_x", "X-Trading-Mode": "paper"},
        )
        assert r.status_code == 403


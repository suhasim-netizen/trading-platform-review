# DRAFT — Pending Security Architect sign-off (P1-03)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brokers.models import AuthToken
from db.base import Base
from db.models import Tenant
from db.session import get_engine, get_session_factory, init_db, reset_engine
from security.crypto import decrypt_secret
from services.broker_credentials_store import BrokerCredentialsStore


def test_two_tenant_token_isolation(tmp_path, monkeypatch):
    # Use isolated sqlite file per test.
    db_path = tmp_path / "iso.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    from config import get_settings

    get_settings.cache_clear()
    reset_engine()

    init_db()
    SessionLocal = get_session_factory()

    with SessionLocal.begin() as s:
        s.add_all([Tenant(tenant_id="tenant_a", display_name="A", status="active"), Tenant(tenant_id="tenant_b", display_name="B", status="active")])

    with SessionLocal.begin() as s:
        store = BrokerCredentialsStore(s)
        store.upsert_tokens(
            tenant_id="tenant_a",
            trading_mode="paper",
            broker_name="tradestation",
            account_id="A-1",
            token=AuthToken(
                tenant_id="tenant_a",
                access_token="a_access",
                refresh_token="a_refresh",
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
            ),
        )
        store.upsert_tokens(
            tenant_id="tenant_b",
            trading_mode="paper",
            broker_name="tradestation",
            account_id="B-1",
            token=AuthToken(
                tenant_id="tenant_b",
                access_token="b_access",
                refresh_token="b_refresh",
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
            ),
        )

    with SessionLocal() as s:
        store = BrokerCredentialsStore(s)
        ct_a = store.get_refresh_token_ciphertext(
            tenant_id="tenant_a", trading_mode="paper", broker_name="tradestation", account_id="A-1"
        )
        ct_b = store.get_refresh_token_ciphertext(
            tenant_id="tenant_b", trading_mode="paper", broker_name="tradestation", account_id="B-1"
        )
        assert ct_a is not None and ct_b is not None
        assert decrypt_secret(ct_a) == "a_refresh"
        assert decrypt_secret(ct_b) == "b_refresh"

        # Cross-tenant read must not work (wrong tenant_id for the same account id).
        ct_cross = store.get_refresh_token_ciphertext(
            tenant_id="tenant_a", trading_mode="paper", broker_name="tradestation", account_id="B-1"
        )
        assert ct_cross is None


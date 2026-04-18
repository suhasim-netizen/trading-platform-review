from __future__ import annotations

from sqlalchemy import select

from db.base import Base
from db.models import Account, Tenant
from db.session import get_engine, get_session_factory, init_db, tenant_scoped_query


def test_tenant_scoped_query_never_returns_other_tenant_rows(test_app) -> None:
    # Ensure tables exist for this isolated SQLite file DB.
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal.begin() as session:
        session.add_all(
            [
                Tenant(tenant_id="tenant_a", display_name="Tenant A", status="active"),
                Tenant(tenant_id="tenant_b", display_name="Tenant B", status="active"),
            ]
        )
        session.flush()

        a1 = Account(tenant_id="tenant_a", trading_mode="paper", broker_account_id="A-1", currency="USD")
        b1 = Account(tenant_id="tenant_b", trading_mode="paper", broker_account_id="B-1", currency="USD")
        session.add_all([a1, b1])

    with SessionLocal() as session:
        stmt = tenant_scoped_query(session, Account, tenant_id="tenant_a", trading_mode="paper")
        rows = session.execute(stmt).scalars().all()
        assert [r.tenant_id for r in rows] == ["tenant_a"]

        # Defense in depth: even if selecting without helper, explicit tenant filter works.
        rows2 = session.execute(select(Account).where(Account.tenant_id == "tenant_a")).scalars().all()
        assert {r.tenant_id for r in rows2} == {"tenant_a"}


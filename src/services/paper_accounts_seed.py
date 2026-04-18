"""Ensure TradeStation paper broker accounts exist in ``accounts`` (for positions FK resolution)."""

from __future__ import annotations

from sqlalchemy import select

from config import get_settings
from db.models import Account, Tenant
from db.session import get_session_factory, init_db


def seed_paper_accounts(tenant_id: str, trading_mode: str) -> int:
    """Insert equity + futures paper accounts from settings if missing. Returns number of rows inserted."""
    init_db()
    settings = get_settings()
    specs: list[tuple[str, str]] = []
    eq = (settings.ts_equity_account_id or "").strip()
    fu = (settings.ts_futures_account_id or "").strip()
    if eq:
        specs.append((eq, "TradeStation Equity Paper"))
    if fu:
        specs.append((fu, "TradeStation Futures Paper"))
    if not specs:
        return 0

    factory = get_session_factory()
    inserted = 0
    with factory() as session:
        with session.begin():
            if session.get(Tenant, tenant_id) is None:
                session.add(Tenant(tenant_id=tenant_id, display_name=tenant_id, status="active"))
            for broker_id, name in specs:
                exists = session.execute(
                    select(Account.id).where(
                        Account.tenant_id == tenant_id,
                        Account.trading_mode == trading_mode,
                        Account.broker_account_id == broker_id,
                    ).limit(1)
                ).scalar_one_or_none()
                if exists is None:
                    session.add(
                        Account(
                            tenant_id=tenant_id,
                            trading_mode=trading_mode,
                            broker_account_id=broker_id,
                            name=name,
                            currency="USD",
                        )
                    )
                    inserted += 1
    if inserted:
        print(f"Seeded {inserted} accounts for tenant {tenant_id}")
    return inserted

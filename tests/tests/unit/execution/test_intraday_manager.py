# PAPER TRADING MODE

"""Intraday PDT window and scheduled flatten."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from brokers.base import BrokerAdapter
from brokers.models import (
    AuthToken,
    BrokerCredentials,
    CancelReceipt,
    Order,
    OrderReceipt,
    OrderStatus,
    Position,
    Quote,
)
from db.models import Tenant
from db.session import get_session_factory, init_db, reset_engine
from execution.intraday_manager import IntradayPositionManager


@pytest.fixture
def pdt_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ipm.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    from config import get_settings

    get_settings.cache_clear()
    reset_engine()
    init_db()
    factory = get_session_factory()
    with factory() as s:
        with s.begin():
            s.add_all(
                [
                    Tenant(tenant_id="t1", display_name="T", status="active"),
                    Tenant(tenant_id="t_iso", display_name="ISO", status="active"),
                ]
            )
    return factory


def test_pdt_limit_blocks_4th_trade(pdt_db):
    # Fixed weekday so rolling window includes traded_at (weekend "now" would drop all counts).
    fixed = datetime(2026, 4, 16, 16, 0, tzinfo=UTC)
    mgr = IntradayPositionManager("paper", clock=lambda: fixed)
    for _ in range(3):
        mgr.record_day_trade("t1", "SPY", traded_at=fixed)
    assert mgr.can_day_trade("t1") is False
    assert mgr.get_remaining_day_trades("t1") == 0


def test_rolling_5_day_window_resets(pdt_db):
    """Older day trades fall outside the rolling 5 business-day window."""
    # Window as of 2026-06-01 should not include Jan / Apr session dates.
    june = datetime(2026, 6, 1, 16, 0, tzinfo=UTC)
    mgr = IntradayPositionManager("paper", clock=lambda: june)
    mgr.record_day_trade("t_iso", "SPY", traded_at=datetime(2026, 1, 6, 16, 0, tzinfo=UTC))
    mgr.record_day_trade("t_iso", "QQQ", traded_at=datetime(2026, 4, 10, 16, 0, tzinfo=UTC))
    assert mgr._day_trade_count("t_iso") == 0
    assert mgr.can_day_trade("t_iso") is True

    apr = datetime(2026, 4, 16, 16, 0, tzinfo=UTC)
    mgr2 = IntradayPositionManager("paper", clock=lambda: apr)
    mgr2.record_day_trade("t1", "A", traded_at=datetime(2026, 4, 14, 16, 0, tzinfo=UTC))
    mgr2.record_day_trade("t1", "B", traded_at=datetime(2026, 4, 15, 16, 0, tzinfo=UTC))
    mgr2.record_day_trade("t1", "C", traded_at=datetime(2026, 4, 16, 15, 0, tzinfo=UTC))
    assert mgr2._day_trade_count("t1") == 3
    assert mgr2.can_day_trade("t1") is False


@pytest.mark.asyncio
async def test_eod_close_triggered_at_1555(pdt_db):
    ny = __import__("zoneinfo").ZoneInfo("America/New_York")
    after_close = datetime(2026, 4, 16, 15, 56, tzinfo=ny)

    class _Ad(BrokerAdapter):
        def __init__(self) -> None:
            self.positions = [
                Position(
                    account_id="ACC",
                    tenant_id="t1",
                    symbol="AVGO",
                    quantity=Decimal("10"),
                )
            ]
            self.placed: list[tuple[Order, str, str]] = []

        async def authenticate(self, credentials: BrokerCredentials) -> AuthToken:
            raise NotImplementedError

        async def refresh_token(self, token: AuthToken) -> AuthToken:
            raise NotImplementedError

        async def get_quote(self, symbol: str, tenant_id: str) -> Quote:
            raise NotImplementedError

        async def get_account(self, account_id: str, tenant_id: str):
            raise NotImplementedError

        async def place_order(self, order: Order, *, tenant_id: str, account_id: str) -> OrderReceipt:
            self.placed.append((order, tenant_id, account_id))
            return OrderReceipt(order_id="o1", tenant_id=tenant_id, status=OrderStatus.SUBMITTED)

        async def cancel_order(self, order_id: str, tenant_id: str) -> CancelReceipt:
            raise NotImplementedError

        async def get_positions(self, account_id: str, tenant_id: str):
            return self.positions

        def stream_quotes(self, symbols: list[str], tenant_id: str):
            raise NotImplementedError

        def stream_bars(self, symbol: str, interval: str, tenant_id: str):
            raise NotImplementedError

        def stream_order_updates(self, account_id: str, tenant_id: str):
            raise NotImplementedError

    ad = _Ad()
    mgr = IntradayPositionManager("paper", account_id="ACC", clock=lambda: after_close)
    await mgr.enforce_eod_close("t1", ad, account_id="ACC")
    assert len(ad.placed) == 1
    assert ad.placed[0][0].symbol == "AVGO"

    before = datetime(2026, 4, 16, 14, 0, tzinfo=ny)
    ad2 = _Ad()
    mgr2 = IntradayPositionManager("paper", account_id="ACC", clock=lambda: before)
    await mgr2.enforce_eod_close("t1", ad2, account_id="ACC")
    assert ad2.placed == []


@pytest.mark.asyncio
async def test_eod_skips_swing_overnight_symbol(pdt_db):
    """strategy_004 swing symbols are not force-closed at 15:55 ET."""
    ny = __import__("zoneinfo").ZoneInfo("America/New_York")
    after_close = datetime(2026, 4, 16, 15, 56, tzinfo=ny)

    class _Ad(BrokerAdapter):
        def __init__(self) -> None:
            self.positions = [
                Position(
                    account_id="ACC",
                    tenant_id="t1",
                    symbol="LASR",
                    quantity=Decimal("100"),
                )
            ]
            self.placed: list[tuple] = []

        async def authenticate(self, credentials):
            raise NotImplementedError

        async def refresh_token(self, token):
            raise NotImplementedError

        async def get_quote(self, symbol: str, tenant_id: str):
            raise NotImplementedError

        async def get_account(self, account_id: str, tenant_id: str):
            raise NotImplementedError

        async def place_order(self, order, *, tenant_id: str, account_id: str):
            self.placed.append((order, tenant_id, account_id))
            return OrderReceipt(order_id="o1", tenant_id=tenant_id, status=OrderStatus.SUBMITTED)

        async def cancel_order(self, order_id: str, tenant_id: str):
            raise NotImplementedError

        async def get_positions(self, account_id: str, tenant_id: str):
            return self.positions

        def stream_quotes(self, symbols: list[str], tenant_id: str):
            raise NotImplementedError

        def stream_bars(self, symbol: str, interval: str, tenant_id: str):
            raise NotImplementedError

        def stream_order_updates(self, account_id: str, tenant_id: str):
            raise NotImplementedError

    ad = _Ad()
    mgr = IntradayPositionManager("paper", account_id="ACC", clock=lambda: after_close)
    await mgr.enforce_eod_close("t1", ad, account_id="ACC")
    assert ad.placed == []


def test_remaining_day_trades_count(pdt_db):
    fixed = datetime(2026, 4, 16, 16, 0, tzinfo=UTC)
    mgr = IntradayPositionManager("paper", clock=lambda: fixed)
    assert mgr.get_remaining_day_trades("t1") == 3
    mgr.record_day_trade("t1", "X", traded_at=fixed)
    assert mgr.get_remaining_day_trades("t1") == 2
    mgr.record_day_trade("t1", "Y", traded_at=fixed)
    assert mgr.get_remaining_day_trades("t1") == 1
    mgr.record_day_trade("t1", "Z", traded_at=fixed)
    assert mgr.get_remaining_day_trades("t1") == 0

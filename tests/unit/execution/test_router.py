# PAPER TRADING MODE

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from brokers.models import Account, OrderReceipt, OrderStatus, OrderUpdate, OrderSide, Quote
from db.base import Base
from db.session import get_engine, init_db, reset_engine
from execution.logger import ExecutionLogger
from execution.models import Signal, SignalType
from execution.router import OrderRouter, RiskPolicy
from execution.tracker import PositionTracker


class _Adapter:
    def __init__(self, *, buying_power: Decimal | None = None, quote_last: Decimal | None = None) -> None:
        self.placed = 0
        self.buying_power = buying_power if buying_power is not None else Decimal("1000000")
        self.quote_last = quote_last if quote_last is not None else Decimal("100")

    async def get_account(self, account_id: str, tenant_id: str) -> Account:  # type: ignore[no-untyped-def]
        return Account(account_id=account_id, tenant_id=tenant_id, buying_power=self.buying_power)

    async def get_quote(self, symbol: str, tenant_id: str) -> Quote:  # type: ignore[no-untyped-def]
        return Quote(tenant_id=tenant_id, symbol=symbol, last=self.quote_last)

    async def place_order(self, order, *, tenant_id: str, account_id: str):  # type: ignore[no-untyped-def]
        self.placed += 1
        return OrderReceipt(order_id="o1", tenant_id=tenant_id, status=OrderStatus.SUBMITTED, submitted_at=datetime.now(UTC))


class _FixedAccountRouter:
    def __init__(self, account_id: str) -> None:
        self._account_id = account_id

    def resolve(self, order, tenant_id: str) -> str:  # type: ignore[no-untyped-def]
        return self._account_id


def _db_setup(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # IMPORTANT: avoid sqlite in-memory + NullPool, which creates a fresh empty DB per connection.
    db_path = tmp_path / "exec_router.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    reset_engine()
    init_db()


@pytest.mark.asyncio
async def test_router_blocks_vix_circuit_breaker(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("10000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", vix=Decimal("31"))

    adapter = _Adapter()
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(),
    )
    sig = Signal(tenant_id="tenant_a", trading_mode="paper", strategy_id="s1", symbol="SPY", signal_type=SignalType.ENTER)
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_router_blocks_daily_loss_limit(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("10000"))
    tracker.set_daily_pnl(
        tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", daily_pnl=Decimal("-300")
    )

    adapter = _Adapter()
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(daily_loss_limit=Decimal("-0.025")),
    )
    sig = Signal(tenant_id="tenant_a", trading_mode="paper", strategy_id="s1", symbol="SPY", signal_type=SignalType.ENTER)
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_router_blocks_max_drawdown(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("10000"))
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("7000"))

    adapter = _Adapter()
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(max_drawdown=Decimal("-0.25")),
    )
    sig = Signal(tenant_id="tenant_a", trading_mode="paper", strategy_id="s1", symbol="SPY", signal_type=SignalType.ENTER)
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_router_blocks_max_positions(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("100000"))
    # Seed 10 open positions
    for i in range(10):
        sym = f"S{i}"
        tracker.set_mark_price(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", symbol=sym, price=Decimal("100"))
        tracker.apply_fill(
            tenant_id="tenant_a",
            trading_mode="paper",
            account_id="A1",
            strategy_id="s1",
            order_id=f"o{i}",
            symbol=sym,
            side=OrderSide.BUY,
            update=OrderUpdate(order_id=f"o{i}", tenant_id="tenant_a", status=OrderStatus.FILLED, filled_quantity=Decimal("1"), avg_fill_price=Decimal("100")),
        )

    adapter = _Adapter()
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(max_positions=10),
    )
    sig = Signal(tenant_id="tenant_a", trading_mode="paper", strategy_id="s1", symbol="NEW", signal_type=SignalType.ENTER)
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_router_blocks_max_position_weight(tmp_path, monkeypatch):
    # "Max size" gate: reject ENTER when the largest position weight is already at/over policy threshold.
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(
        tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("500")
    )
    # One existing $120 position on $1000 NAV => 12% weight (at threshold).
    tracker.set_mark_price(
        tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", symbol="SPY", price=Decimal("120")
    )
    tracker.apply_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        account_id="A1",
        strategy_id="s1",
        order_id="o1",
        symbol="SPY",
        side=OrderSide.BUY,
        update=OrderUpdate(
            order_id="o1",
            tenant_id="tenant_a",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
            avg_fill_price=Decimal("120"),
        ),
    )

    adapter = _Adapter()
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(max_position_weight=Decimal("0.12")),
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="s1",
        symbol="QQQ",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_router_blocks_insufficient_buying_power(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("10000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", vix=Decimal("20"))

    # 1 share @ $100 => need $100; 95% of $50 BP = $47.5 → blocked
    adapter = _Adapter(buying_power=Decimal("50"), quote_last=Decimal("100"))
    logger = ExecutionLogger(tenant_id="tenant_a", trading_mode="paper")
    router = OrderRouter(
        tenant_id="tenant_a",
        trading_mode="paper",
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
        account_router=_FixedAccountRouter("A1"),  # type: ignore[arg-type]
        policy=RiskPolicy(),
    )
    sig = Signal(tenant_id="tenant_a", trading_mode="paper", strategy_id="s1", symbol="SPY", signal_type=SignalType.ENTER)
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


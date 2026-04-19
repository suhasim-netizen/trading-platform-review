# PAPER TRADING MODE

"""Per-strategy realized daily P&L caps (execution_fills joined to execution_orders)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from brokers.models import Account, OrderReceipt, OrderStatus
from db.models import ExecutionFill, ExecutionOrder, Tenant
from db.session import get_session_factory, init_db, reset_engine
from execution.logger import ExecutionLogger
from execution.models import Signal, SignalType
from execution.router import OrderRouter, RiskPolicy
from execution.tracker import PositionTracker


class _Adapter:
    def __init__(self) -> None:
        self.placed = 0

    async def get_account(self, account_id: str, tenant_id: str) -> Account:  # type: ignore[no-untyped-def]
        return Account(account_id=account_id, tenant_id=tenant_id, buying_power=Decimal("100000"))

    async def get_quote(self, symbol: str, tenant_id: str):  # type: ignore[no-untyped-def]
        from brokers.models import Quote

        return Quote(tenant_id=tenant_id, symbol=symbol, last=Decimal("100"))

    async def place_order(self, order, *, tenant_id: str, account_id: str) -> OrderReceipt:  # type: ignore[no-untyped-def]
        self.placed += 1
        return OrderReceipt(order_id="ok1", tenant_id=tenant_id, status=OrderStatus.SUBMITTED)


class _FixedAccountRouter:
    def __init__(self, account_id: str) -> None:
        self._account_id = account_id

    def resolve(self, order, tenant_id: str) -> str:  # type: ignore[no-untyped-def]
        return self._account_id


def _db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/rpnl.db")
    reset_engine()
    init_db()


def _ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=ZoneInfo("America/New_York"))


def _seed_fill(
    *,
    tenant_id: str,
    trading_mode: str,
    strategy_id: str,
    order_id: str,
    side: str,
    fill_price: Decimal,
    fill_qty: Decimal,
    filled_at: datetime,
) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            if session.get(Tenant, tenant_id) is None:
                session.add(Tenant(tenant_id=tenant_id, display_name=tenant_id, status="active"))
            session.add(
                ExecutionOrder(
                    tenant_id=tenant_id,
                    trading_mode=trading_mode,
                    strategy_id=strategy_id,
                    order_id=order_id,
                    symbol="SPY",
                    side=side,
                    quantity=fill_qty,
                    order_type="market",
                    status="filled",
                    raw=None,
                )
            )
            session.add(
                ExecutionFill(
                    tenant_id=tenant_id,
                    trading_mode=trading_mode,
                    order_id=order_id,
                    fill_price=fill_price,
                    fill_qty=fill_qty,
                    filled_at=filled_at,
                    is_snapshot=False,
                    raw=None,
                )
            )


@pytest.mark.asyncio
async def test_strategy_007_blocks_enter_at_negative_1000_pnl(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        order_id="o-loss",
        side="buy",
        fill_price=Decimal("1000"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        symbol="SPY",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_strategy_007_allows_enter_at_negative_999_pnl(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        order_id="o-loss",
        side="buy",
        fill_price=Decimal("999"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        symbol="SPY",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is not None
    assert adapter.placed == 1


@pytest.mark.asyncio
async def test_strategy_004_blocks_enter_at_negative_1500_pnl(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_004",
        order_id="o4",
        side="buy",
        fill_price=Decimal("1500"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_004", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_004", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_004",
        symbol="SPY",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is None
    assert adapter.placed == 0


@pytest.mark.asyncio
async def test_strategy_004_allows_enter_at_negative_1499_pnl(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_004",
        order_id="o4",
        side="buy",
        fill_price=Decimal("1499"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_004", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_004", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_004",
        symbol="SPY",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is not None
    assert adapter.placed == 1


@pytest.mark.asyncio
async def test_unknown_strategy_uses_generic_risk_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="custom_x",
        order_id="ox",
        side="buy",
        fill_price=Decimal("50000"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="custom_x", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="custom_x", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="custom_x",
        symbol="SPY",
        signal_type=SignalType.ENTER,
    )
    rec = await router.route(sig)
    assert rec is not None
    assert adapter.placed == 1


@pytest.mark.asyncio
async def test_strategy_daily_loss_does_not_block_exit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path, monkeypatch)
    clock = _ny(2026, 6, 15, 10, 0)
    _seed_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        order_id="o-loss",
        side="buy",
        fill_price=Decimal("5000"),
        fill_qty=Decimal("1"),
        filled_at=clock.astimezone(UTC),
    )
    tracker = PositionTracker()
    tracker.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", cash=Decimal("100000"))
    tracker.update_vix(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="strategy_007", vix=Decimal("18"))
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
        risk_pnl_clock=clock,
    )
    sig = Signal(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="strategy_007",
        symbol="SPY",
        signal_type=SignalType.EXIT,
    )
    rec = await router.route(sig)
    assert rec is not None
    assert adapter.placed == 1

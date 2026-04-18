# PAPER TRADING MODE

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from brokers.models import Account, Bar, OrderReceipt, OrderSide, OrderStatus, OrderUpdate, Quote
from db.base import Base
from db.models import ExecutionFill, ExecutionOrder, ExecutionSignal
from db.session import get_engine, get_session_factory, init_db, reset_engine
from execution.logger import ExecutionLogger
from execution.models import Signal, SignalType
from execution.router import OrderRouter
from execution.runner import StrategyRunner
from execution.tracker import PositionTracker
from strategies.base import StrategyMeta, StrategyOwnerKind
from strategies.registry import register


class _Sub:
    def __init__(self, msgs: list[str]) -> None:
        self._msgs = msgs

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        for m in self._msgs:
            yield m


class _Adapter:
    def __init__(self) -> None:
        self.last_order_symbol: str | None = None

    async def get_account(self, account_id: str, tenant_id: str) -> Account:  # type: ignore[no-untyped-def]
        return Account(account_id=account_id, tenant_id=tenant_id, buying_power=Decimal("1000000"))

    async def get_quote(self, symbol: str, tenant_id: str) -> Quote:  # type: ignore[no-untyped-def]
        return Quote(tenant_id=tenant_id, symbol=symbol, last=Decimal("100"))

    async def place_order(self, order, *, tenant_id: str, account_id: str):  # type: ignore[no-untyped-def]
        self.last_order_symbol = order.symbol
        return OrderReceipt(order_id="ord-1", tenant_id=tenant_id, status=OrderStatus.SUBMITTED, submitted_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_end_to_end_bar_signal_order_fill_position(tmp_path, monkeypatch):
    db_path = tmp_path / "exec.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    from config import get_settings

    get_settings.cache_clear()
    reset_engine()
    init_db()

    register(StrategyMeta(strategy_id="s1", name="S1", owner_kind=StrategyOwnerKind.PLATFORM, owner_id="director"))

    tenant_id = "tenant_a"
    trading_mode = "paper"
    account_id = "A1"

    now = datetime.now(UTC)
    bar = Bar(
        tenant_id=tenant_id,
        symbol="SPY",
        interval="1d",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        bar_start=now,
        bar_end=now + timedelta(days=1),
    )
    msgs = [json.dumps(bar.model_dump(mode="json"))]

    tracker = PositionTracker()
    tracker.set_cash(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id="s1", cash=Decimal("1000"))
    tracker.set_mark_price(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id="s1", symbol="SPY", price=Decimal("100"))

    logger = ExecutionLogger(tenant_id=tenant_id, trading_mode=trading_mode)
    adapter = _Adapter()
    router = OrderRouter(
        tenant_id=tenant_id,
        trading_mode=trading_mode,
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
    )

    def _sig(bar: Bar, meta):  # type: ignore[no-untyped-def]
        return [
            Signal(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                strategy_id="s1",
                symbol=bar.symbol,
                signal_type=SignalType.ENTER,
                signal_strength=Decimal("1"),
            )
        ]

    runner = StrategyRunner(
        tenant_id=tenant_id,
        trading_mode=trading_mode,
        strategy_id="s1",
        symbol="SPY",
        interval="1d",
        subscriber=_Sub(msgs),
        router=router,
        signal_fn=_sig,
    )
    await runner.run(max_bars=1)

    # Simulate a fill coming from broker order stream.
    upd = OrderUpdate(
        order_id="ord-1",
        tenant_id=tenant_id,
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("1"),
        avg_fill_price=Decimal("100"),
        event_time=datetime.now(UTC),
    )
    logger.log_fill(update=upd, raw={"source": "test"})
    tracker.apply_fill(
        tenant_id=tenant_id,
        trading_mode=trading_mode,
        account_id=account_id,
        strategy_id="s1",
        order_id="ord-1",
        symbol="SPY",
        side=OrderSide.BUY,
        update=upd,
    )

    # Verify DB persistence is tenant-scoped.
    factory = get_session_factory()
    with factory() as s:
        sigs = s.query(ExecutionSignal).filter_by(tenant_id=tenant_id, trading_mode=trading_mode).all()
        orders = s.query(ExecutionOrder).filter_by(tenant_id=tenant_id, trading_mode=trading_mode).all()
        fills = s.query(ExecutionFill).filter_by(tenant_id=tenant_id, trading_mode=trading_mode).all()
        assert len(sigs) == 1
        assert len(orders) == 1
        assert len(fills) == 1

    m = tracker.metrics(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id="s1")
    assert m["nav"] == Decimal("1100")


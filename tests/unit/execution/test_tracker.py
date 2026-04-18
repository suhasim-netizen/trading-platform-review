# PAPER TRADING MODE

from __future__ import annotations

from decimal import Decimal

from brokers.models import OrderSide, OrderStatus, OrderUpdate
from execution.tracker import PositionTracker


def test_tracker_apply_fill_delta_and_nav():
    tr = PositionTracker()
    tr.set_cash(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", cash=Decimal("1000"))
    tr.set_mark_price(
        tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1", symbol="SPY", price=Decimal("100")
    )

    up1 = OrderUpdate(
        order_id="o1",
        tenant_id="tenant_a",
        status=OrderStatus.PARTIALLY_FILLED,
        filled_quantity=Decimal("1"),
        avg_fill_price=Decimal("100"),
    )
    tr.apply_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        account_id="A1",
        strategy_id="s1",
        order_id="o1",
        symbol="SPY",
        side=OrderSide.BUY,
        update=up1,
    )
    m1 = tr.metrics(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1")
    assert m1["nav"] == Decimal("1100")

    # Cumulative filled qty moves to 2 -> delta=1 (not +2)
    up2 = up1.model_copy(update={"filled_quantity": Decimal("2")})
    tr.apply_fill(
        tenant_id="tenant_a",
        trading_mode="paper",
        account_id="A1",
        strategy_id="s1",
        order_id="o1",
        symbol="SPY",
        side=OrderSide.BUY,
        update=up2,
    )
    m2 = tr.metrics(tenant_id="tenant_a", trading_mode="paper", account_id="A1", strategy_id="s1")
    assert m2["nav"] == Decimal("1200")


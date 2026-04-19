# PAPER TRADING MODE

"""Order routing + pre-trade risk enforcement.

ADR 0002: All risk limits enforced before calling BrokerAdapter.place_order.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from brokers.base import BrokerAdapter
from brokers.models import InstrumentType, Order, OrderReceipt, OrderSide, OrderType, Quote, TimeInForce
from sqlalchemy import and_, case, func, select
from zoneinfo import ZoneInfo

from db.models import ExecutionFill, ExecutionOrder as DbExecutionOrder
from db.session import get_session_factory

from .account_router import AccountRouter
from .logger import ExecutionLogger
from .models import RiskDecision, Signal, SignalType
from .tracker import PositionTracker

# Approved per-strategy realized P&L caps (USD, negative = loss). None → no extra cap.
STRATEGY_DAILY_LOSS_LIMITS: dict[str, float] = {
    "strategy_004": -1500.0,
    "strategy_007": -1000.0,
}


def _et_day_start_utc(clock: datetime | None = None) -> datetime:
    """Midnight America/New_York for the calendar day of ``clock`` (or now), as UTC."""
    et = ZoneInfo("America/New_York")
    ref = datetime.now(et) if clock is None else clock.astimezone(et)
    d = ref.date()
    return datetime.combine(d, datetime.min.time(), tzinfo=et).astimezone(UTC)


def _sync_strategy_daily_pnl(
    tenant_id: str,
    trading_mode: str,
    strategy_id: str,
    *,
    clock: datetime | None = None,
) -> float:
    """Sum signed fill notionals for today (ET day): SELL +px×qty, BUY -px×qty (cash-flow proxy)."""
    start = _et_day_start_utc(clock)
    sign_expr = case(
        (DbExecutionOrder.side == "sell", ExecutionFill.fill_price * ExecutionFill.fill_qty),
        else_=-ExecutionFill.fill_price * ExecutionFill.fill_qty,
    )
    stmt = (
        select(func.coalesce(func.sum(sign_expr), 0))
        .select_from(ExecutionFill)
        .join(
            DbExecutionOrder,
            and_(
                DbExecutionOrder.order_id == ExecutionFill.order_id,
                DbExecutionOrder.tenant_id == ExecutionFill.tenant_id,
                DbExecutionOrder.trading_mode == ExecutionFill.trading_mode,
            ),
        )
        .where(
            ExecutionFill.tenant_id == tenant_id,
            ExecutionFill.trading_mode == trading_mode,
            DbExecutionOrder.strategy_id == strategy_id,
            ExecutionFill.is_snapshot.is_(False),
            ExecutionFill.filled_at >= start,
        )
    )
    factory = get_session_factory()
    with factory() as session:
        row = session.execute(stmt).scalar_one()
    return float(row or 0)


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    # Strategy 001 defaults from ADR 0002 §4 (paper).
    max_drawdown: Decimal = Decimal("-0.25")
    daily_loss_limit: Decimal = Decimal("-0.025")
    max_position_weight: Decimal = Decimal("0.12")
    max_positions: int = 10
    vix_off_gt: Decimal = Decimal("30")
    vix_on_le: Decimal = Decimal("28")


class OrderRouter:
    def __init__(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        adapter: BrokerAdapter,
        tracker: PositionTracker,
        logger: ExecutionLogger,
        policy: RiskPolicy | None = None,
        account_router: AccountRouter | None = None,
        risk_pnl_clock: datetime | None = None,
    ) -> None:
        if not tenant_id or not trading_mode:
            raise ValueError("tenant_id and trading_mode are required")
        self._tenant_id = tenant_id
        self._trading_mode = trading_mode
        self._adapter = adapter
        self._tracker = tracker
        self._log = logger
        self._policy = policy or RiskPolicy()
        self._acct_router = account_router or AccountRouter()
        self._risk_pnl_clock = risk_pnl_clock

    def _guard(self, signal: Signal) -> None:
        if signal.tenant_id != self._tenant_id or signal.trading_mode != self._trading_mode:
            raise ValueError("tenant mismatch on signal")

    async def _get_strategy_daily_pnl(self, strategy_id: str) -> float:
        """Today's realized cash-flow proxy from fills (ET day), excluding snapshot replays."""
        return await asyncio.to_thread(
            _sync_strategy_daily_pnl,
            self._tenant_id,
            self._trading_mode,
            strategy_id,
            clock=self._risk_pnl_clock,
        )

    async def evaluate_risk(self, signal: Signal, *, account_id: str) -> RiskDecision:
        self._guard(signal)
        acct = account_id.strip()
        if not acct:
            raise ValueError("account_id is required for risk evaluation")
        m = self._tracker.metrics(
            tenant_id=self._tenant_id,
            trading_mode=self._trading_mode,
            account_id=acct,
            strategy_id=signal.strategy_id,
        )
        dd = m["drawdown"]
        if isinstance(dd, Decimal) and dd <= self._policy.max_drawdown:
            return RiskDecision(allowed=False, reason="max_drawdown")
        daily = m["daily_pnl_pct"]
        if isinstance(daily, Decimal) and daily <= self._policy.daily_loss_limit:
            return RiskDecision(allowed=False, reason="daily_loss_limit")

        strat_limit = STRATEGY_DAILY_LOSS_LIMITS.get(signal.strategy_id)
        if (
            strat_limit is not None
            and signal.signal_type in (SignalType.ENTER, SignalType.REBALANCE, SignalType.TARGET_WEIGHTS)
        ):
            pnl = await self._get_strategy_daily_pnl(signal.strategy_id)
            if pnl <= strat_limit:
                print(f"[RISK] {signal.strategy_id} daily loss limit hit")
                print(
                    f"[RISK] realized ${pnl:.0f} <= limit ${strat_limit:.0f} "
                    f"— no new entries until tomorrow"
                )
                return RiskDecision(allowed=False, reason="strategy_daily_loss_limit")

        # NOTE: VIX gating is enforced at strategy level (gap_fade.py, swing_pullback.py).
        # Router-level vix_guard_allows_entries() is not called here — PositionTracker.update_vix()
        # is not wired from live market data in production. Do not re-enable without wiring
        # update_vix() to a live VIX source.

        # Max positions / weight is enforced against current state; reduces are allowed.
        pos_count = int(m["position_count"] or 0)
        if signal.signal_type == SignalType.ENTER and pos_count >= self._policy.max_positions:
            return RiskDecision(allowed=False, reason="max_positions")

        largest = m["largest_weight"]
        if isinstance(largest, Decimal) and largest >= self._policy.max_position_weight:
            # Runner may emit REBALANCE to reduce; block ENTER/upsizes.
            if signal.signal_type == SignalType.ENTER:
                return RiskDecision(allowed=False, reason="max_position_weight")
        return RiskDecision(allowed=True)

    async def _get_available_buying_power(self, tenant_id: str, account_id: str) -> float:
        """Query broker for current buying power (cash / margin availability)."""
        account = await self._adapter.get_account(account_id, tenant_id)
        bp = account.buying_power
        return float(bp) if bp is not None else 0.0

    @staticmethod
    def _reference_price_for_risk(order: Order, quote: Quote) -> Decimal | None:
        """Conservative notional estimate: limit uses limit_price; else last or mid quote."""
        if order.limit_price is not None and order.order_type == OrderType.LIMIT:
            return order.limit_price
        if quote.last is not None:
            return quote.last
        if quote.bid is not None and quote.ask is not None:
            return (quote.bid + quote.ask) / Decimal("2")
        if quote.bid is not None:
            return quote.bid
        if quote.ask is not None:
            return quote.ask
        return None

    async def _buying_power_allows_order(self, *, tenant_id: str, account_id: str, order: Order) -> bool:
        """True if estimated BUY notional fits under 95% of reported buying power."""
        if order.side != OrderSide.BUY:
            return True
        bp = await self._get_available_buying_power(tenant_id, account_id)
        sym = order.symbol.strip()
        try:
            quote = await self._adapter.get_quote(sym, tenant_id)
        except Exception as e:
            print(f"[RISK] Could not fetch quote for {sym}: {e} — skipping buying-power check")
            return True
        px = self._reference_price_for_risk(order, quote)
        if px is None or px <= 0:
            print(f"[RISK] No usable price for {sym} — skipping buying-power check")
            return True
        order_cost = float(order.quantity * px)
        cap = bp * 0.95
        if order_cost > cap:
            print(
                f"[RISK] Insufficient buying power: "
                f"need ${order_cost:.0f}, "
                f"have ${bp:.0f} — order blocked"
            )
            return False
        return True

    async def route(self, signal: Signal) -> OrderReceipt | None:
        """Route a single signal (Phase 2: 1 signal -> 1 order for tests)."""
        self._guard(signal)
        self._log.log_signal(signal)

        order = _signal_to_order(signal)
        account_id = self._acct_router.resolve(order, tenant_id=self._tenant_id)

        decision = await self.evaluate_risk(signal, account_id=account_id)
        if not decision.allowed:
            # Log blocked actions as orders with a synthetic status.
            return None

        if not await self._buying_power_allows_order(
            tenant_id=self._tenant_id, account_id=account_id, order=order
        ):
            return None

        receipt = await self._adapter.place_order(order, tenant_id=self._tenant_id, account_id=account_id)
        self._log.log_order(strategy_id=signal.strategy_id, order=order, receipt=receipt)
        return receipt


def _signal_to_order(signal: Signal) -> Order:
    # Minimal mapping for Phase 2 tests. Strategy 001 sizing happens in strategy logic later.
    params = signal.params or {}
    inst = InstrumentType.EQUITY
    if params.get("instrument_type") == "futures":
        inst = InstrumentType.FUTURES
    elif params.get("instrument_type") == "options":
        inst = InstrumentType.OPTIONS

    osi = params.get("order_side")
    if signal.signal_type in (SignalType.ENTER, SignalType.REBALANCE, SignalType.TARGET_WEIGHTS):
        if osi == "sell":
            side = OrderSide.SELL
        else:
            side = OrderSide.BUY
    else:
        if osi == "buy":
            side = OrderSide.BUY
        else:
            side = OrderSide.SELL

    qty = Decimal("1")
    if signal.signal_strength is not None:
        try:
            qty = max(Decimal("0"), signal.signal_strength)
        except Exception:
            qty = Decimal("1")
    if qty == 0:
        qty = Decimal("1")
    meta: dict[str, Any] = {"generated_at": signal.generated_at.isoformat()}
    if isinstance(params.get("bracket"), dict):
        meta["bracket"] = params["bracket"]
    return Order(
        symbol=signal.symbol,
        instrument_type=inst,
        side=side,
        quantity=qty,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id=signal.strategy_id,
        metadata=meta,
    )



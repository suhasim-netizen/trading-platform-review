# PAPER TRADING MODE

"""Position tracking and real-time metrics (tenant-scoped).

ADR 0002 requires all state keyed by (tenant_id, trading_mode, account_id, strategy_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from brokers.models import OrderSide, OrderUpdate, Position


@dataclass(slots=True)
class _Lot:
    qty: Decimal = Decimal("0")
    avg_cost: Decimal | None = None
    last_price: Decimal | None = None


@dataclass(slots=True)
class _KeyState:
    positions: dict[str, _Lot] = field(default_factory=dict)
    cash: Decimal = Decimal("0")
    nav_peak: Decimal = Decimal("0")
    nav: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    daily_date: date = field(default_factory=lambda: datetime.now(UTC).date())
    # VIX circuit breaker hysteresis state (Strategy 001 thresholds by default).
    vix_enabled: bool = True
    vix_level: Decimal | None = None
    # Track cumulative filled qty per order_id so we can compute deltas.
    _order_filled_qty: dict[str, Decimal] = field(default_factory=dict)


class PositionTracker:
    """In-memory tenant-scoped position tracker (Phase 2)."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str, str, str], _KeyState] = {}

    @staticmethod
    def _k(*, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str) -> tuple[str, str, str, str]:
        if not tenant_id or not trading_mode or not account_id or not strategy_id:
            raise ValueError("tenant_id, trading_mode, account_id, and strategy_id are required")
        return (tenant_id, trading_mode, account_id, strategy_id)

    def _get(self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str) -> _KeyState:
        k = self._k(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        return self._state.setdefault(k, _KeyState())

    def set_cash(self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str, cash: Decimal) -> None:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        st.cash = cash
        self._recalc_metrics(st)

    def set_daily_pnl(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        account_id: str,
        strategy_id: str,
        daily_pnl: Decimal,
    ) -> None:
        """Test/ops hook: set daily P&L directly (percent computed from NAV)."""
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        st.daily_pnl = daily_pnl

    def set_mark_price(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        account_id: str,
        strategy_id: str,
        symbol: str,
        price: Decimal,
    ) -> None:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        lot = st.positions.setdefault(symbol.upper(), _Lot())
        lot.last_price = price
        self._recalc_metrics(st)

    def update_vix(self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str, vix: Decimal) -> None:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        st.vix_level = vix

    def vix_guard_allows_entries(
        self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str, off_gt: Decimal, on_le: Decimal
    ) -> bool:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        if st.vix_level is None:
            return True
        if st.vix_enabled and st.vix_level > off_gt:
            st.vix_enabled = False
        if (not st.vix_enabled) and st.vix_level <= on_le:
            st.vix_enabled = True
        return st.vix_enabled

    def apply_fill(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        account_id: str,
        strategy_id: str,
        order_id: str,
        symbol: str,
        side: OrderSide,
        update: OrderUpdate,
    ) -> None:
        """Apply filled quantity deltas to holdings (broker-agnostic)."""
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        filled_total = update.filled_quantity
        if filled_total is None:
            return
        prev = st._order_filled_qty.get(order_id, Decimal("0"))
        delta = Decimal(str(filled_total)) - prev
        if delta == 0:
            return
        st._order_filled_qty[order_id] = Decimal(str(filled_total))

        sym = symbol.upper()
        lot = st.positions.setdefault(sym, _Lot())
        signed = delta if side == OrderSide.BUY else -delta

        px = update.avg_fill_price
        if px is not None:
            pxd = Decimal(str(px))
            if lot.qty == 0 or lot.avg_cost is None:
                lot.avg_cost = pxd
            else:
                # VWAP update on position increases in the same direction.
                if (lot.qty > 0 and signed > 0) or (lot.qty < 0 and signed < 0):
                    new_qty = lot.qty + signed
                    if new_qty != 0:
                        lot.avg_cost = ((lot.avg_cost * lot.qty) + (pxd * signed)) / new_qty
        lot.qty = lot.qty + signed
        self._recalc_metrics(st)

    def snapshot_positions(
        self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str
    ) -> list[Position]:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        out: list[Position] = []
        for sym, lot in st.positions.items():
            if lot.qty == 0:
                continue
            mv = (lot.last_price * lot.qty) if lot.last_price is not None else None
            out.append(
                Position(
                    account_id=account_id,
                    tenant_id=tenant_id,
                    symbol=sym,
                    quantity=lot.qty,
                    avg_cost=lot.avg_cost,
                    market_value=mv,
                    updated_at=datetime.now(UTC),
                )
            )
        return out

    def metrics(
        self, *, tenant_id: str, trading_mode: str, account_id: str, strategy_id: str
    ) -> dict[str, Decimal | int | bool | None]:
        st = self._get(tenant_id=tenant_id, trading_mode=trading_mode, account_id=account_id, strategy_id=strategy_id)
        self._roll_daily_if_needed(st)
        largest_w = self._largest_weight(st)
        dd = self._drawdown(st)
        daily_pct = (st.daily_pnl / st.nav) if st.nav > 0 else Decimal("0")
        pos_count = sum(1 for lot in st.positions.values() if lot.qty != 0)
        return {
            "nav": st.nav,
            "nav_peak": st.nav_peak,
            "drawdown": dd,
            "daily_pnl": st.daily_pnl,
            "daily_pnl_pct": daily_pct,
            "largest_weight": largest_w,
            "position_count": pos_count,
            "vix": st.vix_level,
            "vix_enabled": st.vix_enabled,
        }

    def _roll_daily_if_needed(self, st: _KeyState) -> None:
        today = datetime.now(UTC).date()
        if st.daily_date != today:
            st.daily_date = today
            st.daily_pnl = Decimal("0")

    def _recalc_metrics(self, st: _KeyState) -> None:
        self._roll_daily_if_needed(st)
        nav = st.cash
        for lot in st.positions.values():
            if lot.last_price is not None and lot.qty != 0:
                nav += lot.last_price * lot.qty
        st.nav = nav
        if st.nav_peak == 0:
            st.nav_peak = nav
        else:
            st.nav_peak = max(st.nav_peak, nav)

    @staticmethod
    def _drawdown(st: _KeyState) -> Decimal:
        if st.nav_peak <= 0:
            return Decimal("0")
        return (st.nav - st.nav_peak) / st.nav_peak

    @staticmethod
    def _largest_weight(st: _KeyState) -> Decimal:
        if st.nav <= 0:
            return Decimal("0")
        best = Decimal("0")
        for lot in st.positions.values():
            if lot.last_price is None or lot.qty == 0:
                continue
            w = abs(lot.last_price * lot.qty) / st.nav
            best = max(best, w)
        return best



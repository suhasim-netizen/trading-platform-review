# PAPER TRADING MODE

"""Intraday lifecycle: PDT day-trade counts and scheduled flatten before cash close (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from brokers.base import BrokerAdapter
from brokers.models import InstrumentType, Order, OrderSide, OrderType, TimeInForce

from db.models import DayTradeLog
from db.session import get_session_factory

# Intraday-only strategies: EOD flatten applies to their symbols. Swing (strategy_004) is excluded.
INTRADAY_STRATEGIES: tuple[str, ...] = (
    "strategy_002",  # momentum — intraday only
    "strategy_006",  # futures — intraday only
)


def _norm_symbol(sym: str) -> str:
    return sym.strip().upper().lstrip("@")


def intraday_eod_flatten_symbols() -> frozenset[str]:
    """Normalized symbols for positions that must flatten before equity cash close (15:55 ET)."""
    from strategies.futures_intraday import FuturesIntradayStrategy
    from strategies.momentum import EquityMomentumStrategy

    out: set[str] = set()
    for s in getattr(EquityMomentumStrategy, "symbols", []) or []:
        out.add(_norm_symbol(str(s)))
    for s in getattr(FuturesIntradayStrategy, "symbols", []) or []:
        out.add(_norm_symbol(str(s)))
    return frozenset(out)


def _ny_date(dt: datetime) -> date:
    return dt.astimezone(ZoneInfo("America/New_York")).date()


def _rolling_business_dates(as_of: datetime, *, periods: int = 5) -> set[date]:
    """Last ``periods`` weekdays ending at ``as_of`` (NYSE holiday-free v1 — weekdays only)."""
    end_d = _ny_date(as_of)
    days: list[date] = []
    d = end_d
    while len(days) < periods:
        if d.weekday() < 5:
            days.append(d)
        d = d - timedelta(days=1)
    return set(days)


class IntradayPositionManager:
    """PDT tracking and equity session flatten policy (no vendor-specific APIs)."""

    def __init__(
        self,
        trading_mode: str,
        *,
        account_id: str | None = None,
        session_factory: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        pdt_equity_below_25k: bool = True,
    ) -> None:
        self._trading_mode = trading_mode
        self._account_id = account_id
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pdt_equity_below_25k = pdt_equity_below_25k

    def _sf(self):
        return self._session_factory or get_session_factory()

    def record_day_trade(self, tenant_id: str, symbol: str, *, traded_at: datetime | None = None) -> None:
        """Record a completed day trade (open + close same session) for PDT counting."""
        ts = traded_at or self._clock()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        factory = self._sf()
        with factory() as session:
            with session.begin():
                session.add(
                    DayTradeLog(
                        id=str(uuid4()),
                        tenant_id=tenant_id,
                        symbol=symbol.strip(),
                        traded_at=ts,
                        trading_mode=self._trading_mode,
                    )
                )

    def _day_trade_count(self, tenant_id: str) -> int:
        as_of = self._clock()
        window = _rolling_business_dates(as_of)
        factory = self._sf()
        with factory() as session:
            rows = session.execute(
                select(DayTradeLog).where(
                    DayTradeLog.tenant_id == tenant_id,
                    DayTradeLog.trading_mode == self._trading_mode,
                )
            ).scalars().all()
        n = 0
        for r in rows:
            if _ny_date(r.traded_at) in window:
                n += 1
        return n

    def can_day_trade(self, tenant_id: str) -> bool:
        """False when 3 day trades already fall in the rolling 5 business-day window (PDT path)."""
        if not self._pdt_equity_below_25k:
            return True
        return self._day_trade_count(tenant_id) < 3

    def get_remaining_day_trades(self, tenant_id: str) -> int:
        """Returns how many day trades remain before the rolling-window cap (0–3)."""
        if not self._pdt_equity_below_25k:
            return 3
        used = self._day_trade_count(tenant_id)
        return max(0, 3 - used)

    async def enforce_eod_close(
        self,
        tenant_id: str,
        adapter: BrokerAdapter,
        close_time: str = "15:55",
        *,
        account_id: str | None = None,
    ) -> None:
        """Close open positions at or after ``close_time`` America/New_York (market flatten)."""
        acct = account_id or self._account_id
        if not acct:
            raise ValueError("account_id is required (pass to enforce_eod_close or IntradayPositionManager(...))")

        ny = ZoneInfo("America/New_York")
        now_ny = self._clock().astimezone(ny)
        hh, mm = (int(close_time.split(":")[0]), int(close_time.split(":")[1]))
        close_dt = now_ny.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now_ny < close_dt:
            return

        flatten_syms = intraday_eod_flatten_symbols()
        positions = await adapter.get_positions(acct, tenant_id)
        for p in positions:
            if _norm_symbol(p.symbol) not in flatten_syms:
                continue
            qty = p.quantity
            if qty == 0:
                continue
            side = OrderSide.SELL if qty > 0 else OrderSide.BUY
            order = Order(
                symbol=p.symbol,
                side=side,
                quantity=abs(qty),
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                instrument_type=InstrumentType.EQUITY,
            )
            await adapter.place_order(order, tenant_id=tenant_id, account_id=acct)

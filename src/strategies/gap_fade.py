# PAPER TRADING MODE

"""Strategy 007 — Equity overnight gap fade (approved parameters v0.2.0)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")


def _parse_ts(bar: dict[str, Any]) -> datetime | None:
    ts_raw = bar.get("timestamp")
    if isinstance(ts_raw, str):
        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    if isinstance(ts_raw, datetime):
        return ts_raw
    return None


def _f(x: Any) -> float:
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


class GapFadeStrategy:
    """Gap fade: short-only vs gap-up, VIX 15–20, 0.75–2.0% gap, 11:00 ET time stop."""

    name = "strategy_007"
    strategy_id = "strategy_007"
    symbols = [
        "TSLA",
        "MSFT",
        "AAPL",
        "AMZN",
        "META",
        "NFLX",
        "HOOD",
        "QQQ",
        "INTC",
        "QCOM",
        "PLTR",
        "ZS",
        "SHOP",
        "UBER",
        "GOOGL",
    ]
    interval = "15m"

    GAP_MIN_PCT = 0.75
    GAP_MAX_PCT = 2.0
    VIX_MIN = 15.0
    VIX_MAX = 20.0
    SIDE_MODE = "short"
    TIME_STOP_HOUR = 11
    TIME_STOP_MIN = 0
    STOP_MULTIPLIER = 1.5
    TARGET_MULTIPLIER = 2.0
    RISK_PER_TRADE_PCT = 0.005
    ACCOUNT_EQUITY = 20000
    MAX_POSITIONS = 2

    def __init__(self) -> None:
        self._prev_close: dict[str, float] = {}
        self._gap_pct: dict[str, float] = {}
        self._position: dict[str, str | None] = {}
        self._position_shares: dict[str, int] = {}
        self._traded_today: dict[str, bool] = {}
        self._opening_evaluated: dict[str, bool] = {}
        self._entry_price: dict[str, float] = {}
        self._stop_price: dict[str, float] = {}
        self._target_price: dict[str, float] = {}
        self._last_close: dict[str, float] = {}
        self._last_session_date: dict[str, date] = {}
        self._vix_today: float | None = None
        self._vix_fetched_date: date | None = None
        self._adapter: Any = None
        self._tenant_id: str | None = None

    def set_broker_context(self, adapter: Any, tenant_id: str) -> None:
        """Called by platform after adapter is ready."""
        self._adapter = adapter
        self._tenant_id = tenant_id

    async def prefetch_session_data_async(self, bar: dict[str, Any]) -> None:
        """Fetch daily VIX once per ET session (before ``on_bar``)."""
        ts = _parse_ts(bar)
        if ts is None or self._adapter is None or not self._tenant_id:
            return
        d = ts.astimezone(_NY).date()
        if self._vix_fetched_date == d:
            return
        vx = await self._fetch_vix_async()
        if vx is not None and vx == 0.0:
            print("[GAP] VIX=0 invalid — treating as unavailable (fail safe)")
            vx = None
        self._vix_today = vx
        self._vix_fetched_date = d
        if self._vix_today is not None:
            print(f"[GAP] VIX today: {self._vix_today:.2f}")

    async def _fetch_vix_async(self) -> float | None:
        """Last daily VIX close via TradeStation ``GET /v3/marketdata/barcharts/{symbol}``.

        Uses ``$VIX.X`` (TradeStation CBOE VIX index symbol). If barcharts return no
        rows in your subscription, try ``VIX``, ``$VIX``, or ``^VIX`` and update the
        literal below — see ``scripts/verify_ts_vix_and_streams.py`` for a probe.
        """
        if self._adapter is None or not self._tenant_id:
            return None
        fetch = getattr(self._adapter, "fetch_barcharts_rest", None)
        if fetch is None:
            print("[GAP] VIX fetch: adapter has no fetch_barcharts_rest")
            return None
        try:
            rows = await fetch(
                "$VIX.X",
                self._tenant_id,
                interval="1",
                unit="Daily",
                barsback=1,
            )
            if not rows:
                return None
            last = rows[-1]
            c = last.get("Close") or last.get("close") or last.get("Last")
            if c is None:
                return None
            return float(c)
        except Exception as e:
            print(f"[GAP] VIX fetch failed: {e}")
            return None

    def update_position(self, symbol: str, side: str | None) -> None:
        sym = symbol.strip().upper().lstrip("@")
        self._position[sym] = side

    def _open_short_count(self) -> int:
        return sum(1 for s in self.symbols if self._position.get(s.strip().upper()) == "short")

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        sym = symbol.strip().upper()
        if sym not in self.symbols:
            return None

        ts = _parse_ts(bar)
        if ts is None:
            return None
        ts_ny = ts.astimezone(_NY)
        bar_date = ts_ny.date()
        # STEP 1 — new session
        if bar_date != self._last_session_date.get(sym):
            if sym in self._last_close:
                self._prev_close[sym] = self._last_close[sym]
            self._traded_today[sym] = False
            self._opening_evaluated[sym] = False
            self._position[sym] = None
            self._position_shares.pop(sym, None)
            self._gap_pct[sym] = 0.0
            self._last_session_date[sym] = bar_date

        close = _f(bar["close"])
        open_ = _f(bar["open"])

        # STEP 2 — track last close
        self._last_close[sym] = close

        # Time stop / EOD (before 09:30 entry logic)
        if self._position.get(sym) == "short":
            h, m = ts_ny.hour, ts_ny.minute
            if h > self.TIME_STOP_HOUR or (h == self.TIME_STOP_HOUR and m >= self.TIME_STOP_MIN):
                self._position[sym] = None
                q = max(1, int(self._position_shares.pop(sym, 1)))
                print(f"[GAP] {sym} TIME STOP 11:00 ET — flatten")
                return {
                    "action": "buy_to_cover",
                    "symbol": sym,
                    "quantity": q,
                    "strategy_id": self.strategy_id,
                    "instrument_type": "equity",
                    "order_side": "buy",
                }
            if h > 15 or (h == 15 and m >= 55):
                self._position[sym] = None
                q = max(1, int(self._position_shares.pop(sym, 1)))
                print(f"[GAP] {sym} EOD 15:55 ET — flatten")
                return {
                    "action": "buy_to_cover",
                    "symbol": sym,
                    "quantity": q,
                    "strategy_id": self.strategy_id,
                    "instrument_type": "equity",
                    "order_side": "buy",
                }

        # Only first 15m bar (09:30) evaluates gap entry
        if ts_ny.hour != 9 or ts_ny.minute != 30:
            return None

        if self._opening_evaluated.get(sym):
            return None

        self._opening_evaluated[sym] = True

        prev_close = self._prev_close.get(sym, 0.0)
        if prev_close == 0.0:
            return None

        gap_pct = (open_ - prev_close) / prev_close * 100.0
        self._gap_pct[sym] = gap_pct

        if not (self.GAP_MIN_PCT <= gap_pct <= self.GAP_MAX_PCT):
            print(f"[GAP] {sym} gap {gap_pct:.2f}% outside 0.75-2.0% — skip")
            self._traded_today[sym] = True
            return None

        vix = self._vix_today
        if vix is not None and vix == 0.0:
            print("[GAP] VIX=0 invalid — treating as unavailable (fail safe)")
            vix = None
        if vix is None:
            print(f"[GAP] {sym} VIX unavailable — skip (fail safe)")
            self._traded_today[sym] = True
            return None

        if not (self.VIX_MIN <= vix <= self.VIX_MAX):
            print(f"[GAP] {sym} VIX {vix:.1f} outside 15-20 — skip")
            self._traded_today[sym] = True
            return None

        if gap_pct <= 0:
            print(f"[GAP] {sym} gap down {gap_pct:.2f}% — long side disabled in approved config")
            self._traded_today[sym] = True
            return None

        bar_close = close
        if bar_close > prev_close:
            print(f"[GAP] {sym} gap up but price holding — no confirmation, skip")
            self._traded_today[sym] = True
            return None

        if self._open_short_count() >= self.MAX_POSITIONS:
            print(f"[GAP] {sym} max positions ({self.MAX_POSITIONS}) — skip")
            self._traded_today[sym] = True
            return None

        entry = bar_close
        abs_gap = abs(gap_pct)
        stop_dist = abs_gap * self.STOP_MULTIPLIER / 100.0 * entry
        target_dist = abs_gap * self.TARGET_MULTIPLIER / 100.0 * entry
        if stop_dist <= 0:
            self._traded_today[sym] = True
            return None

        stop = entry + stop_dist
        target = entry - target_dist

        risk_amount = self.ACCOUNT_EQUITY * self.RISK_PER_TRADE_PCT
        shares = int(risk_amount / stop_dist)
        cap = int(self.ACCOUNT_EQUITY / entry) if entry > 0 else 1
        shares = max(1, min(shares, cap))

        self._position[sym] = "short"
        self._traded_today[sym] = True
        self._position_shares[sym] = shares
        self._entry_price[sym] = entry
        self._stop_price[sym] = stop
        self._target_price[sym] = target

        print(
            f"[GAP] {sym} SHORT gap={gap_pct:.2f}% VIX={vix:.1f} "
            f"entry={entry:.2f} stop={stop:.2f} target={target:.2f} shares={shares}"
        )

        return {
            "action": "sell_short",
            "symbol": sym,
            "quantity": Decimal(str(shares)),
            "strategy_id": self.strategy_id,
            "instrument_type": "equity",
            "order_side": "sell",
            "bracket": {"stop": round(stop, 2), "target": round(target, 2)},
        }


HANDLER_CLASS = GapFadeStrategy

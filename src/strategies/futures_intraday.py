# PAPER TRADING MODE

"""Strategy 006 — Futures intraday VWAP / ATR bands / RSI per docs/strategies/strategy_006_v0.1.0.md."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from config import get_settings

_NY = ZoneInfo("America/New_York")

# Conservative day-margin estimates per 1 micro contract (USD) for pre-trade checks.
_MARGIN_MES = Decimal("250")
_MARGIN_MNQ = Decimal("200")


def _d(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _wilder_rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(ch if ch > 0 else Decimal("0"))
        losses.append(-ch if ch < 0 else Decimal("0"))
    if len(gains) < period:
        return None
    avg_g = sum(gains[:period]) / Decimal(period)
    avg_l = sum(losses[:period]) / Decimal(period)
    for i in range(period, len(gains)):
        avg_g = (avg_g * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_l = (avg_l * Decimal(period - 1) + losses[i]) / Decimal(period)
    if avg_l == 0:
        return Decimal("100")
    rs = avg_g / avg_l
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


class FuturesIntradayStrategy:
    name = "strategy_006"
    symbols = ["@MES", "@MNQ"]
    interval = "1m"

    def __init__(self) -> None:
        self.session_date: date | None = None
        self.cum_tp_vol = Decimal("0")
        self.cum_vol = Decimal("0")
        self.session_closes: list[Decimal] = []
        self.session_highs: list[Decimal] = []
        self.session_lows: list[Decimal] = []
        self.atr: Decimal | None = None
        self.tr_buffer: list[Decimal] = []
        self._bar_count: dict[str, int] = {}
        # Symbol-level direction awareness (survives runner restarts via TradingPlatform startup restore).
        # Values: "long" | "short" | None
        self._positions: dict[str, str | None] = {}
        self.prev_upper: Decimal | None = None
        self.prev_lower: Decimal | None = None
        self.prev_close: Decimal | None = None

    def _norm_sym(self, s: str) -> str:
        """Map stream/contract symbols (e.g. MESM26) to strategy roots MES / MNQ."""
        s = s.strip().upper().lstrip("@")
        if s.startswith("MES"):
            return "MES"
        if s.startswith("MNQ"):
            return "MNQ"
        if s.startswith("ES") and not s.startswith("MES"):
            return "ES"
        if s.startswith("NQ") and not s.startswith("MNQ"):
            return "NQ"
        return s

    def _estimated_margin_for_one_contract(self, root: str) -> Decimal:
        if root == "MES":
            return _MARGIN_MES
        if root == "MNQ":
            return _MARGIN_MNQ
        return Decimal("5000")

    def _reset_session(self, d: date) -> None:
        self.session_date = d
        self.cum_tp_vol = Decimal("0")
        self.cum_vol = Decimal("0")
        self.session_closes = []
        self.session_highs = []
        self.session_lows = []
        self.tr_buffer = []
        self.atr = None
        self._bar_count = {}
        self.prev_upper = None
        self.prev_lower = None
        self.prev_close = None

    def update_position(self, symbol: str, side: str | None) -> None:
        """Startup hook: restore current position direction from broker (source of truth)."""
        sym = self._norm_sym(symbol)
        if side not in ("long", "short", None):
            return
        self._positions[sym] = side

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        sym = self._norm_sym(symbol)
        allowed = {self._norm_sym(s) for s in self.symbols}
        if sym not in allowed:
            return None

        try:
            budget = get_settings().futures_margin_budget_usd
        except Exception:
            budget = Decimal("22800")
        if self._estimated_margin_for_one_contract(sym) > budget:
            return None

        ts_raw = bar.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            return None
        ts_ny = ts.astimezone(_NY)
        d = ts_ny.date()
        if self.session_date != d:
            self._reset_session(d)

        o, h, l, c = (_d(bar["open"]), _d(bar["high"]), _d(bar["low"]), _d(bar["close"]))
        vol = _d(bar.get("volume", "0"))
        if vol < 0:
            vol = Decimal("0")

        self._bar_count[sym] = self._bar_count.get(sym, 0) + 1

        tp = (h + l + c) / Decimal("3")
        self.cum_tp_vol += tp * vol
        self.cum_vol += vol
        if self.cum_vol <= 0:
            vwap = tp
        else:
            vwap = self.cum_tp_vol / self.cum_vol

        self.session_closes.append(c)
        self.session_highs.append(h)
        self.session_lows.append(l)

        # VWAP needs a meaningful sample; early bars are noisy.
        if self._bar_count[sym] < 30:
            n = self._bar_count[sym]
            if n == 1 or n % 5 == 0:
                print(f"[WARMUP] {sym} bar {n}/30")
            self.prev_close = c
            return None

        # Require price to be at least 0.1% away from VWAP (avoid 1-tick noise).
        if vwap != 0:
            vwap_distance_pct = abs(c - vwap) / vwap
            if vwap_distance_pct < Decimal("0.001"):
                self.prev_close = c
                return None

        # Wilder ATR(14) on session bars
        if len(self.session_closes) == 1:
            tr = h - l
        else:
            pc = self.session_closes[-2]
            tr = max(h - l, abs(h - pc), abs(l - pc))
        self.tr_buffer.append(tr)
        n = 14
        if len(self.tr_buffer) >= n:
            if len(self.tr_buffer) == n:
                self.atr = sum(self.tr_buffer[:n]) / Decimal(n)
            else:
                prev_atr = self.atr if self.atr is not None else sum(self.tr_buffer[-n - 1 : -1]) / Decimal(n)
                self.atr = (prev_atr * Decimal(n - 1) + tr) / Decimal(n)

        rsi = _wilder_rsi(self.session_closes, 14)
        if self.atr is None or rsi is None:
            self.prev_close = c
            return None

        upper = vwap + Decimal("0.5") * self.atr
        lower = vwap - Decimal("0.5") * self.atr

        sig: dict[str, Any] | None = None
        pc = self.prev_close
        pu = self.prev_upper
        pl = self.prev_lower

        if pc is not None and pu is not None and pl is not None:
            long_x = pc <= pu and c > upper and rsi > Decimal("55")
            short_x = pc >= pl and c < lower and rsi < Decimal("45")
            current = self._positions.get(sym)
            if current == "long" and long_x and not short_x:
                self.prev_upper = upper
                self.prev_lower = lower
                self.prev_close = c
                return None
            if current == "short" and short_x and not long_x:
                self.prev_upper = upper
                self.prev_lower = lower
                self.prev_close = c
                return None

            if current is None and long_x and not short_x:
                sig = {
                    "action": "buy",
                    "symbol": sym,
                    "quantity": Decimal("1"),
                    "strategy_id": self.name,
                    "instrument_type": "futures",
                }
                self._positions[sym] = "long"
            elif current is None and short_x and not long_x:
                sig = {
                    "action": "sell",
                    "symbol": sym,
                    "quantity": Decimal("1"),
                    "strategy_id": self.name,
                    "instrument_type": "futures",
                    "order_side": "sell",
                }
                self._positions[sym] = "short"

        self.prev_upper = upper
        self.prev_lower = lower
        self.prev_close = c
        return sig


HANDLER_CLASS = FuturesIntradayStrategy

# PAPER TRADING MODE

"""Strategy 002 — Equity momentum intraday per docs/strategies/strategy_002_v0.2.0.md."""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, time as time_of_day
from decimal import ROUND_DOWN, Decimal
from typing import Any

from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")

_ENTRY_START = time_of_day(9, 35)
_ENTRY_END = time_of_day(14, 0)
_EOD_FLAT = time_of_day(15, 55)


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


def _parse_ts(bar: dict[str, Any]) -> datetime | None:
    ts_raw = bar.get("timestamp")
    if isinstance(ts_raw, str):
        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    if isinstance(ts_raw, datetime):
        return ts_raw
    return None


class EquityMomentumStrategy:
    name = "strategy_002"
    symbols = ["AVGO", "LLY", "TSM", "GEV"]
    interval = "5m"

    def __init__(self) -> None:
        self.closes: dict[str, deque[Decimal]] = {}
        self.highs: dict[str, deque[Decimal]] = {}
        self.lows: dict[str, deque[Decimal]] = {}
        self.volumes: dict[str, deque[Decimal]] = {}
        self.positions: dict[str, Decimal] = {}
        self.entry_prices: dict[str, Decimal] = {}
        self.high_close_since: dict[str, Decimal] = {}
        self.trail_armed: dict[str, bool] = {}
        self._prev_bar_high: dict[str, Decimal | None] = {}
        self._session_date: dict[str, date | None] = {}
        self._cum_tp_vol: dict[str, Decimal] = {}
        self._cum_vol: dict[str, Decimal] = {}
        self._risk_dollars = Decimal("500")
        self._max_notional = Decimal("25000")
        self._max_positions = 2

    def _ensure(self, sym: str) -> None:
        if sym not in self.closes:
            self.closes[sym] = deque(maxlen=260)
            self.highs[sym] = deque(maxlen=260)
            self.lows[sym] = deque(maxlen=260)
            self.volumes[sym] = deque(maxlen=260)

    def _vol_mean_20(self, sym: str) -> Decimal | None:
        v = self.volumes[sym]
        if len(v) < 20:
            return None
        return sum(list(v)[-20:]) / Decimal(20)

    def _sma20(self, sym: str) -> Decimal | None:
        c = self.closes[sym]
        if len(c) < 20:
            return None
        return sum(list(c)[-20:]) / Decimal(20)

    def _session_vwap(self, sym: str, h: Decimal, l: Decimal, c: Decimal, vol: Decimal) -> Decimal | None:
        tp = (h + l + c) / Decimal("3")
        cum_v = self._cum_vol.get(sym, Decimal("0"))
        cum_tv = self._cum_tp_vol.get(sym, Decimal("0"))
        if vol > 0:
            cum_v += vol
            cum_tv += tp * vol
            self._cum_vol[sym] = cum_v
            self._cum_tp_vol[sym] = cum_tv
        if cum_v <= 0:
            return None
        return cum_tv / cum_v

    def _open_position_count(self) -> int:
        return sum(1 for q in self.positions.values() if q and q > 0)

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        sym = symbol.strip().upper()
        if sym not in self.symbols:
            return None

        ts = _parse_ts(bar)
        if ts is None:
            return None
        ts_ny = ts.astimezone(_NY)
        d = ts_ny.date()
        tclock = ts_ny.time()

        if self._session_date.get(sym) != d:
            self._session_date[sym] = d
            self._cum_tp_vol[sym] = Decimal("0")
            self._cum_vol[sym] = Decimal("0")

        close = _d(bar["close"])
        high = _d(bar["high"])
        low = _d(bar["low"])
        vol = _d(bar.get("volume", "0"))

        self._ensure(sym)
        self.closes[sym].append(close)
        self.highs[sym].append(high)
        self.lows[sym].append(low)
        self.volumes[sym].append(vol)

        vwap = self._session_vwap(sym, high, low, close, vol)
        vol20 = self._vol_mean_20(sym)
        closes = list(self.closes[sym])
        rsi = _wilder_rsi(closes, 14)
        prev_high = self._prev_bar_high.get(sym)

        pos = self.positions.get(sym, Decimal("0"))

        # --- exits (long only) ---
        if pos > 0:
            entry = self.entry_prices.get(sym, close)
            # Hard EOD 15:55 ET
            if tclock >= _EOD_FLAT:
                q = pos
                self.positions[sym] = Decimal("0")
                self.entry_prices.pop(sym, None)
                self.high_close_since.pop(sym, None)
                self.trail_armed.pop(sym, None)
                self._prev_bar_high[sym] = high
                return {"action": "sell", "symbol": sym, "quantity": q, "strategy_id": self.name}

            stop_px = entry * (Decimal("1") - Decimal("0.08"))
            tgt_px = entry * Decimal("1.03")
            hc = max(self.high_close_since.get(sym, close), close)
            self.high_close_since[sym] = hc

            if low <= stop_px:
                q = pos
                self.positions[sym] = Decimal("0")
                self._clear_leg(sym)
                self._prev_bar_high[sym] = high
                return {"action": "sell", "symbol": sym, "quantity": q, "strategy_id": self.name}

            sma20 = self._sma20(sym)
            if sma20 is not None and close < sma20:
                q = pos
                self.positions[sym] = Decimal("0")
                self._clear_leg(sym)
                self._prev_bar_high[sym] = high
                return {"action": "sell", "symbol": sym, "quantity": q, "strategy_id": self.name}

            if high >= tgt_px:
                q = pos
                self.positions[sym] = Decimal("0")
                self._clear_leg(sym)
                self._prev_bar_high[sym] = high
                return {"action": "sell", "symbol": sym, "quantity": q, "strategy_id": self.name}

            if hc >= entry * Decimal("1.02"):
                self.trail_armed[sym] = True
            if self.trail_armed.get(sym):
                trail = hc * (Decimal("1") - Decimal("0.01"))
                eff_stop = max(stop_px, trail)
                if close <= eff_stop or low <= eff_stop:
                    q = pos
                    self.positions[sym] = Decimal("0")
                    self._clear_leg(sym)
                    self._prev_bar_high[sym] = high
                    return {"action": "sell", "symbol": sym, "quantity": q, "strategy_id": self.name}

        # --- entries ---
        self._prev_bar_high[sym] = high

        if pos > 0 or vol20 is None or vol20 <= 0 or vwap is None or rsi is None or prev_high is None:
            return None

        if not (_ENTRY_START <= tclock <= _ENTRY_END):
            return None

        if self._open_position_count() >= self._max_positions and pos <= 0:
            return None

        surge = vol > vol20 * Decimal("1.5")
        breakout = close > prev_high
        trend = close > vwap
        mom = rsi > Decimal("55")

        if pos <= 0 and breakout and surge and trend and mom:
            risk_px = close * Decimal("0.015")
            if risk_px <= 0:
                return None
            shares = (self._risk_dollars / risk_px).quantize(Decimal("1"), rounding=ROUND_DOWN)
            max_sh = (self._max_notional / close).quantize(Decimal("1"), rounding=ROUND_DOWN)
            shares = min(shares, max_sh)
            if shares < 1:
                return None
            self.positions[sym] = shares
            self.entry_prices[sym] = close
            self.high_close_since[sym] = close
            self.trail_armed[sym] = False
            return {
                "action": "buy",
                "symbol": sym,
                "quantity": shares,
                "strategy_id": self.name,
            }

        return None

    def _clear_leg(self, sym: str) -> None:
        self.entry_prices.pop(sym, None)
        self.high_close_since.pop(sym, None)
        self.trail_armed.pop(sym, None)


HANDLER_CLASS = EquityMomentumStrategy

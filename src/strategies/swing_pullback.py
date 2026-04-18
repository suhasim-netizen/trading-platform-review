# PAPER TRADING MODE

"""Strategy 004 — Equity swing pullback per docs/strategies/strategy_004_v0.1.0.md (simplified v0)."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any


def _d(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


class EquitySwingStrategy:
    name = "strategy_004"
    symbols = ["LASR", "LITE", "COHR", "SNDK", "STRL"]
    interval = "1D"

    def __init__(self) -> None:
        self.closes: dict[str, deque[Decimal]] = {}
        self.lows: dict[str, deque[Decimal]] = {}
        self.volumes: dict[str, deque[Decimal]] = {}
        self.positions: dict[str, Decimal] = {}
        self.entry_prices: dict[str, Decimal] = {}
        self.bars_in_trade: dict[str, int] = {}
        self._per_cap = Decimal("6250")

    def _ensure(self, symbol: str) -> None:
        if symbol not in self.closes:
            self.closes[symbol] = deque(maxlen=260)
            self.lows[symbol] = deque(maxlen=260)
            self.volumes[symbol] = deque(maxlen=260)

    def _sma(self, values: deque[Decimal], n: int) -> Decimal | None:
        if len(values) < n:
            return None
        tail = list(values)[-n:]
        return sum(tail, Decimal("0")) / Decimal(n)

    def _pullback_on_prior_bar(self, symbol: str, bars_back: int) -> bool:
        """Pullback on bar t-k (bars_back=1 => t-1) per §4.2."""
        c = list(self.closes[symbol])
        low = list(self.lows[symbol])
        if len(c) < bars_back + 10:
            return False
        p = len(c) - 1 - bars_back
        if p < 0:
            return False
        prev = c[: p + 1]
        if len(prev) < 10:
            return False
        sma10 = sum(prev[-10:]) / Decimal(10)
        if sma10 <= 0:
            return False
        lp = low[p]
        band = abs(lp - sma10) / sma10 <= Decimal("0.01")
        return band and lp <= sma10

    def _pullback_recent(self, symbol: str) -> bool:
        return self._pullback_on_prior_bar(symbol, 1) or self._pullback_on_prior_bar(symbol, 2)

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        sym = symbol.strip().upper()
        if sym not in self.symbols:
            return None

        close = _d(bar["close"])
        low = _d(bar["low"])
        vol = _d(bar.get("volume", "0"))
        high = _d(bar.get("high", close))

        self._ensure(sym)
        self.closes[sym].append(close)
        self.lows[sym].append(low)
        self.volumes[sym].append(vol)

        c = self.closes[sym]
        v = self.volumes[sym]
        sma50 = self._sma(c, 50)
        sma10 = self._sma(c, 10)
        v20 = self._sma(v, 20)
        if sma50 is None or sma10 is None or v20 is None or v20 <= 0:
            return None

        pos = self.positions.get(sym, Decimal("0"))

        # Exits when in position
        if pos > 0:
            entry = self.entry_prices.get(sym, close)
            self.bars_in_trade[sym] = self.bars_in_trade.get(sym, 0) + 1
            bt = self.bars_in_trade[sym]
            tp = entry * Decimal("1.08")
            sl = entry * Decimal("0.96")
            if high >= tp or close <= sl or bt >= 10:
                q = pos
                self.positions[sym] = Decimal("0")
                self.entry_prices.pop(sym, None)
                self.bars_in_trade.pop(sym, None)
                return {
                    "action": "sell",
                    "symbol": sym,
                    "quantity": q,
                    "strategy_id": self.name,
                }

        if pos > 0:
            return None

        # Entry
        pullback_ok = self._pullback_recent(sym)
        vol_ok = vol > v20 * Decimal("1.2")
        uptrend = close > sma50 and close > sma10
        if uptrend and pullback_ok and vol_ok:
            shares = (self._per_cap / close).quantize(Decimal("1"), rounding="ROUND_DOWN")
            if shares < 1:
                return None
            self.positions[sym] = shares
            self.entry_prices[sym] = close
            self.bars_in_trade[sym] = 1
            return {
                "action": "buy",
                "symbol": sym,
                "quantity": shares,
                "strategy_id": self.name,
            }

        return None


HANDLER_CLASS = EquitySwingStrategy

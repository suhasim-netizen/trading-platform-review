# PAPER TRADING MODE

"""Strategy 004 — Equity swing pullback v0.2.1 (Variant D) per docs/backtests/backtest_004_v0.2.1.md."""

from __future__ import annotations

from collections import deque
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from zoneinfo import ZoneInfo

from brokers.models import InstrumentType, Order, OrderSide, OrderType, TimeInForce
from execution.account_router import AccountRouter

_NY = ZoneInfo("America/New_York")

VIX_MIN = 15.0
VIX_MAX = 30.0
MAX_HOLD_DAYS = 20
MAX_POSITIONS = 2
ACCOUNT_EQUITY = 30000
NOTIONAL_CAP = Decimal(str(ACCOUNT_EQUITY))
ATR_PERIOD = 14
ATR_STOP_MULT = Decimal("2")
ATR_TARGET_MULT = Decimal("4")
# Fallback when ATR(14) unavailable (insufficient history): matches legacy v0.1.0 % exits
FALLBACK_STOP_PCT = Decimal("0.96")
FALLBACK_TARGET_PCT = Decimal("1.08")

# Feature flag — Variant D is long-only (shorts disabled)
ENABLE_SHORTS = False


def _d(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _parse_ts(bar: dict[str, Any]) -> datetime | None:
    ts_raw = bar.get("timestamp")
    if isinstance(ts_raw, str):
        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    if isinstance(ts_raw, datetime):
        return ts_raw
    return None


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


class EquitySwingStrategy:
    name = "strategy_004"
    strategy_id = "strategy_004"
    version = "0.2.1"
    symbols = [
        "NVDA",
        "ARM",
        "AVGO",
        "AMD",
        "SMCI",
        "GEV",
        "LLY",
        "MU",
        "TSM",
        "ORCL",
        "CRM",
        "ADBE",
        "NOW",
        "PANW",
        "CRWD",
        "SNOW",
        "DDOG",
        "HUBS",
    ]
    interval = "1D"
    ENABLE_SHORTS = ENABLE_SHORTS

    def __init__(self) -> None:
        self.closes: dict[str, deque[Decimal]] = {}
        self.highs: dict[str, deque[Decimal]] = {}
        self.lows: dict[str, deque[Decimal]] = {}
        self.volumes: dict[str, deque[Decimal]] = {}
        # Signed quantity: >0 long, <0 short
        self.positions: dict[str, Decimal] = {}
        self.entry_prices: dict[str, Decimal] = {}
        self.entry_dates: dict[str, date] = {}
        self.entry_atr: dict[str, Decimal] = {}
        self._price_history: dict[str, list[dict[str, float]]] = {}
        self._adapter: Any = None
        self._tenant_id: str | None = None
        self._vix_today: float | None = None
        self._vix_fetched_date: date | None = None
        self._earnings_filter_logged = False
        self._stop_order_ids: dict[str, str] = {}

    def set_broker_context(self, adapter: Any, tenant_id: str) -> None:
        self._adapter = adapter
        self._tenant_id = tenant_id

    async def prefetch_session_data_async(self, bar: dict[str, Any]) -> None:
        ts = _parse_ts(bar)
        if ts is None or self._adapter is None or not self._tenant_id:
            return
        d = ts.astimezone(_NY).date()
        if self._vix_fetched_date == d:
            return
        vx = await self._fetch_vix_async()
        if vx is not None and vx == 0.0:
            print("[SWING] VIX=0 invalid — treating as unavailable (fail safe)")
            vx = None
        self._vix_today = vx
        self._vix_fetched_date = d
        if self._vix_today is not None:
            print(f"[SWING] VIX session: {self._vix_today:.2f}")

    async def _fetch_vix_async(self) -> float | None:
        if self._adapter is None or not self._tenant_id:
            return None
        fetch = getattr(self._adapter, "fetch_barcharts_rest", None)
        if fetch is None:
            print("[SWING] VIX: adapter has no fetch_barcharts_rest")
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
            print(f"[SWING] VIX fetch failed: {e}")
            return None

    def _session_vix_normalized(self, sym: str) -> float | None:
        v = self._vix_today
        if v is not None and v == 0.0:
            print(f"[SWING] {sym} VIX=0 invalid — treating as unavailable (skip)")
            return None
        return v

    def update_position(self, symbol: str, side: str | None) -> None:
        sym = symbol.strip().upper().lstrip("@")
        if side == "short":
            self.positions[sym] = -Decimal("1")
        elif side == "long":
            self.positions[sym] = Decimal("1")
        else:
            self.positions[sym] = Decimal("0")

    def _ensure(self, symbol: str) -> None:
        if symbol not in self.closes:
            self.closes[symbol] = deque(maxlen=260)
            self.highs[symbol] = deque(maxlen=260)
            self.lows[symbol] = deque(maxlen=260)
            self.volumes[symbol] = deque(maxlen=260)
            self._price_history[symbol] = []

    def _sma(self, values: deque[Decimal], n: int) -> Decimal | None:
        if len(values) < n:
            return None
        tail = list(values)[-n:]
        return sum(tail, Decimal("0")) / Decimal(n)

    def _compute_atr(self, symbol: str, period: int = ATR_PERIOD) -> float:
        bars = self._price_history.get(symbol, [])
        if len(bars) < period + 1:
            return 0.0
        true_ranges: list[float] = []
        for i in range(1, len(bars)):
            high = bars[i]["high"]
            low = bars[i]["low"]
            prev_close = bars[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        return sum(true_ranges[-period:]) / period

    def _pullback_on_prior_bar(self, symbol: str, bars_back: int = 1) -> bool:
        """Long: prior bar HIGH within 1% of SMA10 (as of that bar) and HIGH >= SMA10."""
        sym = symbol.strip().upper()
        bars = self._price_history.get(sym, [])
        if len(bars) < bars_back + 1:
            return False
        prior_bar = bars[-(bars_back + 1)]
        prior_high = float(prior_bar.get("high", 0.0))
        c = list(self.closes[sym])
        if len(c) < bars_back + 10:
            return False
        closes_asof = c[:-bars_back] if bars_back else c
        if len(closes_asof) < 10:
            return False
        sma10 = sum(closes_asof[-10:]) / Decimal(10)
        if sma10 <= 0:
            return False
        ph = Decimal(str(prior_high))
        distance_pct = abs(ph - sma10) / sma10
        return distance_pct <= Decimal("0.01") and ph >= sma10

    def _pullback_recent(self, symbol: str) -> bool:
        return self._pullback_on_prior_bar(symbol, 1) or self._pullback_on_prior_bar(symbol, 2)

    def _resistance_touch_on_prior_bar(self, symbol: str, bars_back: int) -> bool:
        """Short: high within 1% of SMA10 and at/above SMA10 on bar t-k."""
        c = list(self.closes[symbol])
        h = list(self.highs[symbol])
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
        hp = h[p]
        band = abs(float(hp - sma10) / float(sma10)) <= 0.01
        return band and hp >= sma10

    def _resistance_pullback_recent(self, symbol: str) -> bool:
        return self._resistance_touch_on_prior_bar(symbol, 1) or self._resistance_touch_on_prior_bar(symbol, 2)

    def _open_position_count(self) -> int:
        return sum(1 for s in self.symbols if self.positions.get(s.strip().upper(), Decimal("0")) != 0)

    def _bar_date_et(self, bar: dict[str, Any]) -> date | None:
        ts = _parse_ts(bar)
        if ts is None:
            return None
        return ts.astimezone(_NY).date()

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        sym = symbol.strip().upper()
        if sym not in self.symbols:
            return None

        if not self._earnings_filter_logged:
            print("[SWING] EARNINGS_FILTER_OFF — calendar not wired")
            self._earnings_filter_logged = True

        close = _d(bar["close"])
        low = _d(bar["low"])
        high = _d(bar.get("high", close))
        vol = _d(bar.get("volume", "0"))

        self._ensure(sym)
        self.closes[sym].append(close)
        self.highs[sym].append(high)
        self.lows[sym].append(low)
        self.volumes[sym].append(vol)
        self._price_history[sym].append(
            {
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "open": float(_d(bar.get("open", close))),
            }
        )
        if len(self._price_history[sym]) > 260:
            self._price_history[sym] = self._price_history[sym][-260:]

        c = self.closes[sym]
        v = self.volumes[sym]
        sma10 = self._sma(c, 10)
        sma50 = self._sma(c, 50)
        sma200 = self._sma(c, 200)
        v20 = self._sma(v, 20)
        if sma10 is None or sma50 is None or v20 is None or v20 <= 0:
            return None

        bar_d = self._bar_date_et(bar)
        if bar_d is None:
            return None

        pos = self.positions.get(sym, Decimal("0"))

        # --- exits ---
        if pos != 0:
            entry = self.entry_prices.get(sym, close)
            atr_e = self.entry_atr.get(sym, Decimal("0"))
            ed = self.entry_dates.get(sym)
            days_held = (bar_d - ed).days if ed is not None else 0
            q = abs(pos)

            if pos > 0:
                if atr_e > 0:
                    stop_px = entry - ATR_STOP_MULT * atr_e
                    tgt_px = entry + ATR_TARGET_MULT * atr_e
                else:
                    stop_px = entry * FALLBACK_STOP_PCT
                    tgt_px = entry * FALLBACK_TARGET_PCT
                hit_time = days_held >= MAX_HOLD_DAYS
                exit_long = False
                if close <= stop_px or high >= tgt_px:
                    exit_long = True
                elif hit_time:
                    print(f"[SWING] {sym} max hold 20d — flatten")
                    exit_long = True
                if exit_long:
                    self.positions[sym] = Decimal("0")
                    self._clear_leg(sym)
                    return {
                        "action": "sell",
                        "symbol": sym,
                        "quantity": q,
                        "strategy_id": self.strategy_id,
                        "instrument_type": "equity",
                    }
            elif pos < 0:
                if atr_e > 0:
                    stop_px = entry + ATR_STOP_MULT * atr_e
                    tgt_px = entry - ATR_TARGET_MULT * atr_e
                else:
                    stop_px = entry * (Decimal("2") - FALLBACK_STOP_PCT)
                    tgt_px = entry * (Decimal("2") - FALLBACK_TARGET_PCT)
                hit_time = days_held >= MAX_HOLD_DAYS
                exit_short = False
                if low <= tgt_px or close >= stop_px:
                    exit_short = True
                elif hit_time:
                    print(f"[SWING] {sym} max hold 20d — flatten")
                    exit_short = True
                if exit_short:
                    self.positions[sym] = Decimal("0")
                    self._clear_leg(sym)
                    return {
                        "action": "buy_to_cover",
                        "symbol": sym,
                        "quantity": int(q),
                        "strategy_id": self.strategy_id,
                        "instrument_type": "equity",
                        "order_side": "buy",
                    }

            return None

        # --- new entries (flat): require 200 sessions for SMA200 regime filters ---
        if len(c) < 200 or sma200 is None:
            return None

        closes_list = list(c)
        rsi14 = _wilder_rsi(closes_list, 14)

        # --- new entries (flat) ---
        if self._open_position_count() >= MAX_POSITIONS:
            return None

        vol_ok = vol > v20 * Decimal("1.2")
        atr_f = Decimal(str(self._compute_atr(sym, ATR_PERIOD)))

        if close <= sma200:
            print(f"[SWING] {sym} below SMA200 — skip")

        vix_n = self._session_vix_normalized(sym)
        vix_ok = vix_n is not None and VIX_MIN <= vix_n <= VIX_MAX

        structural_long = (
            close > sma10
            and close > sma50
            and close > sma200
            and sma50 > sma200
            and rsi14 is not None
            and rsi14 > Decimal("55")
            and vol_ok
            and self._open_position_count() < MAX_POSITIONS
            and self._pullback_recent(sym)
        )
        if structural_long:
            if vix_n is None:
                print(f"[SWING] {sym} VIX unavailable — skip")
            elif not vix_ok:
                print(f"[SWING] {sym} VIX={vix_n:.1f} outside 15-30 — skip")

        long_ok = structural_long and vix_ok
        if long_ok:
            if atr_f > 0:
                stop_px = close - ATR_STOP_MULT * atr_f
                tgt_px = close + ATR_TARGET_MULT * atr_f
            else:
                stop_px = close * FALLBACK_STOP_PCT
                tgt_px = close * FALLBACK_TARGET_PCT
            shares = (NOTIONAL_CAP / close).quantize(Decimal("1"))
            if shares < 1:
                return None
            print(
                f"[SWING] {sym} LONG entry={float(close):.2f} stop={float(stop_px):.2f} "
                f"target={float(tgt_px):.2f} atr={float(atr_f):.2f} vix={vix_n:.1f}"
            )
            self.positions[sym] = shares
            self.entry_prices[sym] = close
            self.entry_dates[sym] = bar_d
            self.entry_atr[sym] = atr_f
            return {
                "action": "buy",
                "symbol": sym,
                "quantity": shares,
                "strategy_id": self.strategy_id,
                "instrument_type": "equity",
                "bracket": {
                    "stop": float(stop_px),
                    "target": float(tgt_px),
                },
            }

        # Short (v0.2.0)
        if not self.ENABLE_SHORTS:
            pass
        else:
            short_ok = (
                close < sma50
                and sma50 < sma200
                and self._resistance_pullback_recent(sym)
                and close < sma10
                and rsi14 is not None
                and rsi14 < Decimal("45")
                and vol_ok
            )
            if short_ok:
                shares = (NOTIONAL_CAP / close).quantize(Decimal("1"))
                if shares < 1:
                    return None
                self.positions[sym] = -shares
                self.entry_prices[sym] = close
                self.entry_dates[sym] = bar_d
                self.entry_atr[sym] = atr_f
                return {
                    "action": "sell_short",
                    "symbol": sym,
                    "quantity": shares,
                    "strategy_id": self.strategy_id,
                    "instrument_type": "equity",
                    "order_side": "sell",
                    "bracket": {
                        "stop": float(close + ATR_STOP_MULT * atr_f),
                        "target": float(close - ATR_TARGET_MULT * atr_f),
                    },
                }

        return None

    async def _cancel_gtc_stop_for_symbol(self, sym: str) -> None:
        sym_u = sym.strip().upper()
        oid = self._stop_order_ids.pop(sym_u, None)
        if not oid or self._adapter is None or not self._tenant_id:
            return
        try:
            await self._adapter.cancel_order(oid, self._tenant_id)
            print(f"[STOP_GTC] {sym_u} cancelled protective stop order_id={oid}")
        except Exception as e:
            print(f"[STOP_GTC] {sym_u} cancel failed: {e}")

    async def post_bar_async(self, symbol: str, bar: dict[str, Any]) -> None:
        """Place a broker GTC stop once per open symbol; cancel when the strategy state is flat."""
        sym_u = symbol.strip().upper()
        pos = self.positions.get(sym_u, Decimal("0"))
        if pos == 0:
            if sym_u in self._stop_order_ids:
                await self._cancel_gtc_stop_for_symbol(sym_u)
            return
        if self._adapter is None or not self._tenant_id:
            return
        if sym_u in self._stop_order_ids:
            return
        entry = self.entry_prices.get(sym_u)
        atr_e = self.entry_atr.get(sym_u, Decimal("0"))
        if entry is None:
            return
        if pos > 0:
            if atr_e > 0:
                stop_px = entry - ATR_STOP_MULT * atr_e
            else:
                stop_px = entry * FALLBACK_STOP_PCT
            side = OrderSide.SELL
        else:
            if atr_e > 0:
                stop_px = entry + ATR_STOP_MULT * atr_e
            else:
                stop_px = entry * (Decimal("2") - FALLBACK_STOP_PCT)
            side = OrderSide.BUY
        qty = abs(pos)
        if qty <= 0:
            return
        order = Order(
            symbol=sym_u,
            side=side,
            quantity=qty,
            order_type=OrderType.STOP,
            stop_price=stop_px.quantize(Decimal("0.01")),
            time_in_force=TimeInForce.GTC,
            instrument_type=InstrumentType.EQUITY,
            strategy_id=self.strategy_id,
        )
        acct = AccountRouter().resolve(order, self._tenant_id)
        try:
            receipt = await self._adapter.place_order(order, tenant_id=self._tenant_id, account_id=acct)
        except Exception as e:
            print(f"[STOP_GTC] {sym_u} place_order failed: {e}")
            return
        self._stop_order_ids[sym_u] = receipt.order_id
        print(
            f"[STOP_GTC] {sym_u} GTC stop placed @ {float(stop_px):.2f} — overnight protection "
            f"(order_id={receipt.order_id})"
        )

    def _clear_leg(self, sym: str) -> None:
        self.entry_prices.pop(sym, None)
        self.entry_dates.pop(sym, None)
        self.entry_atr.pop(sym, None)


HANDLER_CLASS = EquitySwingStrategy

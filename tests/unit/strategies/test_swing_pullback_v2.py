# PAPER TRADING MODE

"""Unit tests for strategy_004 EquitySwingStrategy v0.2.1 (Variant D long-only)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from strategies.swing_pullback import (
    ATR_PERIOD,
    ATR_STOP_MULT,
    ATR_TARGET_MULT,
    EquitySwingStrategy,
    MAX_HOLD_DAYS,
    _wilder_rsi,
)

_NY = ZoneInfo("America/New_York")
_SYM = "NVDA"


def _bar(
    *,
    ts: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    vol: float = 1_000_000,
) -> dict:
    return {
        "timestamp": ts.isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    }


def _d(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 16, 0, tzinfo=_NY)


def _sma10_if_close_were(closes_deque, next_close: float) -> Decimal:
    """SMA10 at end of bar if `next_close` is appended (last 9 existing + new)."""
    hist = list(closes_deque)
    tail = hist[-9:] + [Decimal(str(next_close))]
    return sum(tail) / Decimal(10)


def _append_resistance_probe_bar(s: EquitySwingStrategy, ts: datetime, close_frac: float) -> None:
    """Daily bar whose high equals SMA10 including this bar (within band, at resistance)."""
    hist = list(s.closes[_SYM])
    ref = sum(hist[-10:]) / Decimal(10)
    c = float(ref) * close_frac
    sma10 = _sma10_if_close_were(s.closes[_SYM], c)
    h = float(sma10)
    s.on_bar(_SYM, _bar(ts=ts, open_=c, high=h, low=c * 0.99, close=c, vol=1_000_000))


@pytest.fixture
def s() -> EquitySwingStrategy:
    strat = EquitySwingStrategy()
    strat.set_broker_context(object(), "tenant-test")
    strat._vix_today = 18.0
    strat._vix_fetched_date = _d(2026, 4, 1).date()
    return strat


def _seed_downtrend_history(s: EquitySwingStrategy, *, end_day: datetime) -> None:
    """~250 daily bars: flat high plateau then sustained decline; steady volume (no entries)."""
    n = 250
    start = end_day - timedelta(days=n)
    base_vol = 1_000_000.0
    for i in range(n):
        ts = start + timedelta(days=i)
        if i < 80:
            c = 260.0
        else:
            t = (i - 80) / (n - 80 - 1)
            c = 260.0 - 165.0 * t
        h, lo = c * 1.002, c * 0.998
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=h, low=lo, close=c, vol=base_vol))


def test_short_signal_fires_in_downtrend(s: EquitySwingStrategy) -> None:
    s.ENABLE_SHORTS = True  # exercise short path; production default is module ENABLE_SHORTS=False
    end = _d(2026, 6, 15)
    _seed_downtrend_history(s, end_day=end)

    base = end + timedelta(days=1)
    _append_resistance_probe_bar(s, base, close_frac=0.93)
    _append_resistance_probe_bar(s, base + timedelta(days=1), close_frac=0.92)

    hist = list(s.closes[_SYM])
    ref = sum(hist[-10:]) / Decimal(10)
    close_t = float(ref) * 0.88
    spike_vol = 5_000_000.0
    r = s.on_bar(
        _SYM,
        _bar(
            ts=base + timedelta(days=2),
            open_=close_t,
            high=close_t * 1.0001,
            low=close_t * 0.999,
            close=close_t,
            vol=spike_vol,
        ),
    )

    assert r is not None
    assert r["action"] == "sell_short"
    assert r["symbol"] == _SYM
    assert r["strategy_id"] == "strategy_004"
    assert r["instrument_type"] == "equity"
    assert Decimal(str(r["quantity"])) >= 1
    assert "bracket" in r


def test_short_blocked_when_vix_below_15(s: EquitySwingStrategy) -> None:
    s._vix_today = 14.5
    end = _d(2026, 6, 15)
    _seed_downtrend_history(s, end_day=end)

    base = end + timedelta(days=1)
    _append_resistance_probe_bar(s, base, close_frac=0.93)
    _append_resistance_probe_bar(s, base + timedelta(days=1), close_frac=0.92)
    hist = list(s.closes[_SYM])
    ref = sum(hist[-10:]) / Decimal(10)
    close_t = float(ref) * 0.88
    r = s.on_bar(
        _SYM,
        _bar(
            ts=base + timedelta(days=2),
            open_=close_t,
            high=close_t * 1.0001,
            low=close_t * 0.999,
            close=close_t,
            vol=5_000_000,
        ),
    )
    assert r is None


def test_short_blocked_when_vix_above_30(s: EquitySwingStrategy) -> None:
    s._vix_today = 30.5
    end = _d(2026, 6, 15)
    _seed_downtrend_history(s, end_day=end)

    base = end + timedelta(days=1)
    _append_resistance_probe_bar(s, base, close_frac=0.93)
    _append_resistance_probe_bar(s, base + timedelta(days=1), close_frac=0.92)
    hist = list(s.closes[_SYM])
    ref = sum(hist[-10:]) / Decimal(10)
    close_t = float(ref) * 0.88
    r = s.on_bar(
        _SYM,
        _bar(
            ts=base + timedelta(days=2),
            open_=close_t,
            high=close_t * 1.0001,
            low=close_t * 0.999,
            close=close_t,
            vol=5_000_000,
        ),
    )
    assert r is None


def test_long_blocked_when_vix_above_30(s: EquitySwingStrategy) -> None:
    s._vix_today = 31.0
    end = _d(2026, 8, 10)
    n = 249
    start = end - timedelta(days=n)
    base_vol = 1_000_000.0
    for i in range(n - 1):
        ts = start + timedelta(days=i)
        c = 100.0 + i * 0.14 + (0.3 if i >= 230 else 0)
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=c * 1.002, low=c * 0.998, close=c, vol=base_vol))

    ts_prev = end - timedelta(days=1)
    ts_last = end
    c_prev = float(s.closes[_SYM][-1])
    sma10_prev = sum(list(s.closes[_SYM])[-10:]) / Decimal(10)
    high_prev = float(sma10_prev) * 1.002
    s.on_bar(
        _SYM,
        _bar(
            ts=ts_prev,
            open_=c_prev,
            high=high_prev,
            low=c_prev * 0.997,
            close=c_prev,
            vol=base_vol,
        ),
    )
    c_sig = float(s.closes[_SYM][-1]) * 1.012
    r = s.on_bar(
        _SYM,
        _bar(
            ts=ts_last,
            open_=c_sig,
            high=c_sig * 1.002,
            low=c_sig * 0.998,
            close=c_sig,
            vol=2_500_000,
        ),
    )
    assert r is None


def test_atr_stop_calculated_correctly(s: EquitySwingStrategy) -> None:
    sym = _SYM
    s._ensure(sym)
    trs = [2.0, 4.0, 1.0, 5.0, 3.0, 2.0, 6.0, 1.5, 2.5, 4.5, 3.5, 2.2, 1.1, 4.1, 2.8]
    prev_close = 100.0
    for i, tr in enumerate(trs):
        h = prev_close + tr * 0.6
        lo = h - tr
        c = (h + lo) / 2
        s._price_history[sym].append({"high": h, "low": lo, "close": c, "open": prev_close})
        prev_close = c
    expected = sum(trs[-ATR_PERIOD:]) / ATR_PERIOD
    got = s._compute_atr(sym, ATR_PERIOD)
    assert abs(got - expected) < 1e-9


def test_max_hold_20_days_triggers_exit(s: EquitySwingStrategy) -> None:
    s._vix_today = 20.0
    d0 = _d(2026, 1, 4)
    base_vol = 1_000_000.0
    for i in range(250):
        ts = d0 + timedelta(days=i)
        c = 100.0
        s.on_bar(
            _SYM,
            _bar(ts=ts, open_=c, high=c + 1.0, low=c - 1.0, close=c, vol=base_vol),
        )

    entry_day = d0 + timedelta(days=10)
    exit_day = entry_day + timedelta(days=MAX_HOLD_DAYS)
    s.positions[_SYM] = Decimal("10")
    s.entry_prices[_SYM] = Decimal("100")
    s.entry_dates[_SYM] = entry_day.date()
    s.entry_atr[_SYM] = Decimal("1")

    r = s.on_bar(
        _SYM,
        _bar(
            ts=exit_day,
            open_=100.0,
            high=100.5,
            low=99.5,
            close=100.0,
            vol=1_000_000,
        ),
    )
    assert r is not None
    assert r["action"] == "sell"
    assert r["quantity"] == Decimal("10")
    assert s.positions.get(_SYM, Decimal("0")) == 0


def test_long_signal_unchanged_core_rules(s: EquitySwingStrategy) -> None:
    """Long: SMA200/50/10 + RSI>55 + VIX + volume + prior-bar HIGH vs SMA10 (spec)."""
    end = _d(2026, 9, 20)
    n = 249
    start = end - timedelta(days=n)
    base_vol = 1_000_000.0
    for i in range(n - 1):
        ts = start + timedelta(days=i)
        c = 100.0 + i * 0.14 + (0.3 if i >= 230 else 0)
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=c * 1.002, low=c * 0.998, close=c, vol=base_vol))

    ts_prev = end - timedelta(days=1)
    ts_last = end
    c_prev = float(s.closes[_SYM][-1])
    sma10_prev = sum(list(s.closes[_SYM])[-10:]) / Decimal(10)
    high_prev = float(sma10_prev) * 1.002
    s.on_bar(
        _SYM,
        _bar(
            ts=ts_prev,
            open_=c_prev,
            high=high_prev,
            low=c_prev * 0.997,
            close=c_prev,
            vol=base_vol,
        ),
    )
    c_sig = float(s.closes[_SYM][-1]) * 1.012
    r = s.on_bar(
        _SYM,
        _bar(
            ts=ts_last,
            open_=c_sig,
            high=c_sig * 1.002,
            low=c_sig * 0.998,
            close=c_sig,
            vol=2_500_000,
        ),
    )
    assert r is not None
    assert r["action"] == "buy"
    assert r["strategy_id"] == "strategy_004"
    assert r["instrument_type"] == "equity"
    assert r["symbol"] == _SYM
    assert Decimal(str(r["quantity"])) >= 1
    br = r.get("bracket") or {}
    entry = Decimal(str(c_sig))
    atr_est = Decimal(str(s._compute_atr(_SYM, ATR_PERIOD)))
    assert atr_est > 0
    assert br.get("stop") == float(entry - ATR_STOP_MULT * atr_est)
    assert br.get("target") == float(entry + ATR_TARGET_MULT * atr_est)


def test_long_blocked_when_close_below_sma200(s: EquitySwingStrategy) -> None:
    end = _d(2026, 10, 5)
    n = 249
    start = end - timedelta(days=n)
    base_vol = 1_000_000.0
    for i in range(n - 1):
        ts = start + timedelta(days=i)
        c = 100.0 + i * 0.14 + (0.3 if i >= 230 else 0)
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=c * 1.002, low=c * 0.998, close=c, vol=base_vol))
    ts_prev = end - timedelta(days=1)
    c_prev = float(s.closes[_SYM][-1])
    sma10_prev = sum(list(s.closes[_SYM])[-10:]) / Decimal(10)
    high_prev = float(sma10_prev) * 1.002
    s.on_bar(
        _SYM,
        _bar(
            ts=ts_prev,
            open_=c_prev,
            high=high_prev,
            low=c_prev * 0.997,
            close=c_prev,
            vol=base_vol,
        ),
    )
    sma200 = s._sma(s.closes[_SYM], 200)
    assert sma200 is not None
    c_bad = float(sma200) * 0.97
    r = s.on_bar(
        _SYM,
        _bar(
            ts=end,
            open_=c_bad,
            high=c_bad * 1.01,
            low=c_bad * 0.99,
            close=c_bad,
            vol=2_500_000,
        ),
    )
    assert r is None


def test_long_blocked_when_sma50_below_sma200(s: EquitySwingStrategy) -> None:
    end = _d(2026, 6, 15)
    _seed_downtrend_history(s, end_day=end)
    d1 = end + timedelta(days=1)
    c = float(s.closes[_SYM][-1])
    r = s.on_bar(
        _SYM,
        _bar(ts=d1, open_=c, high=c * 1.02, low=c * 0.98, close=c * 1.01, vol=5_000_000),
    )
    assert r is None


def test_long_blocked_when_rsi_below_55(s: EquitySwingStrategy) -> None:
    end = _d(2026, 9, 22)
    start = end - timedelta(days=268)
    base_vol = 1_000_000.0
    for i in range(239):
        ts = start + timedelta(days=i)
        c = 100.0 + i * 0.14 + (0.3 if i >= 220 else 0)
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=c * 1.002, low=c * 0.998, close=c, vol=base_vol))
    for j in range(10):
        ts = start + timedelta(days=239 + j)
        c0 = float(s.closes[_SYM][-1])
        c = c0 * 0.996
        s.on_bar(_SYM, _bar(ts=ts, open_=c, high=c * 1.001, low=c * 0.999, close=c, vol=base_vol))
    ts_prev = end - timedelta(days=1)
    c_prev = float(s.closes[_SYM][-1])
    sma10_prev = sum(list(s.closes[_SYM])[-10:]) / Decimal(10)
    high_prev = float(sma10_prev) * 1.002
    s.on_bar(
        _SYM,
        _bar(
            ts=ts_prev,
            open_=c_prev,
            high=high_prev,
            low=c_prev * 0.997,
            close=c_prev,
            vol=base_vol,
        ),
    )
    rsi_before = _wilder_rsi(list(s.closes[_SYM]), 14)
    assert rsi_before is not None and rsi_before < Decimal("55")
    c_sig = float(s.closes[_SYM][-1]) * 1.008
    r = s.on_bar(
        _SYM,
        _bar(
            ts=end,
            open_=c_sig,
            high=c_sig * 1.002,
            low=c_sig * 0.998,
            close=c_sig,
            vol=2_500_000,
        ),
    )
    assert r is None


@pytest.mark.asyncio
async def test_prefetch_vix_zero_normalized_swing() -> None:
    class Ad:
        async def fetch_barcharts_rest(self, sym: str, tenant: str, **kwargs) -> list[dict]:
            return [{"Close": 0.0}]

    strat = EquitySwingStrategy()
    strat.set_broker_context(Ad(), "t1")
    bar = _bar(ts=_d(2026, 5, 2), open_=1, high=1, low=1, close=1, vol=1)
    await strat.prefetch_session_data_async(bar)
    assert strat._vix_today is None


@pytest.mark.asyncio
async def test_prefetch_vix_async_uses_adapter_and_caches_date() -> None:
    calls: list[tuple[str, str]] = []

    class Ad:
        async def fetch_barcharts_rest(self, sym: str, tenant: str, **kwargs):
            calls.append((sym, tenant))
            return [{"Close": 18.5}]

    strat = EquitySwingStrategy()
    strat.set_broker_context(Ad(), "t-abc")
    bar = _bar(ts=_d(2026, 5, 2), open_=1, high=1, low=1, close=1, vol=1)
    await strat.prefetch_session_data_async(bar)
    await strat.prefetch_session_data_async(bar)
    assert len(calls) == 1
    assert strat._vix_today == 18.5
    assert strat._vix_fetched_date == _d(2026, 5, 2).date()


def test_set_broker_context_stores_adapter_and_tenant(s: EquitySwingStrategy) -> None:
    class Ad:
        pass

    a = Ad()
    s.set_broker_context(a, "tid-99")
    assert s._adapter is a
    assert s._tenant_id == "tid-99"

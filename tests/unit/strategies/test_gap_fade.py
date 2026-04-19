# PAPER TRADING MODE

"""Unit tests for strategy_007 GapFadeStrategy."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from strategies.gap_fade import GapFadeStrategy

_NY = ZoneInfo("America/New_York")


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


def _d(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_NY)


@pytest.fixture
def s() -> GapFadeStrategy:
    g = GapFadeStrategy()
    g._vix_today = 17.0
    g._vix_fetched_date = datetime(2026, 4, 17, 9, 30, tzinfo=_NY).date()
    return g


def test_gap_too_small_no_signal(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._last_close["TSLA"] = 100.0
    s._last_session_date["TSLA"] = d.date()  # same day already reset
    s._prev_close["TSLA"] = 100.0
    # gap 0.5%
    b = _bar(ts=d, open_=100.5, high=101, low=100, close=99.0)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_gap_too_large_no_signal(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=103.0, high=104, low=102, close=101.0)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_vix_too_low_no_signal(s: GapFadeStrategy) -> None:
    s._vix_today = 14.0
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=101.0, high=101.5, low=100.2, close=99.5)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_vix_too_high_no_signal(s: GapFadeStrategy) -> None:
    s._vix_today = 21.0
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=101.0, high=101.5, low=100.2, close=99.5)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_gap_down_short_only_no_signal(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=99.0, high=99.5, low=98.5, close=98.8)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_gap_up_confirmed_short_signal(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    # gap ~1%, close below prev close
    b = _bar(ts=d, open_=101.0, high=101.2, low=99.0, close=99.5)
    r = s.on_bar("TSLA", b)
    assert r is not None
    assert r["action"] == "sell_short"
    assert r["symbol"] == "TSLA"
    assert r["instrument_type"] == "equity"
    assert r["order_side"] == "sell"
    assert "bracket" in r


def test_gap_up_price_holds_no_signal(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=101.0, high=102, low=100.5, close=100.5)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_time_stop_flatten(s: GapFadeStrategy) -> None:
    d0 = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b0 = _bar(ts=d0, open_=101.0, high=101.2, low=99.0, close=99.5)
    s.on_bar("TSLA", b0)
    d1 = _d(2026, 4, 17, 11, 0)
    b1 = _bar(ts=d1, open_=99.0, high=100, low=98, close=99.0)
    r = s.on_bar("TSLA", b1)
    assert r is not None
    assert r["action"] == "buy_to_cover"
    assert r["order_side"] == "buy"


def test_time_stop_no_position_none(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 11, 0)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=100.5, high=101, low=100, close=100.2)
    r = s.on_bar("TSLA", b)
    assert r is None


def test_position_sizing(s: GapFadeStrategy) -> None:
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["MSFT"] = 100.0
    b = _bar(ts=d, open_=101.0, high=101.2, low=99.0, close=99.5)
    r = s.on_bar("MSFT", b)
    assert r is not None
    entry = 99.5
    gap_pct = 1.0
    stop_dist = gap_pct * 1.5 / 100.0 * entry
    risk = 20000 * 0.005
    expect = int(risk / stop_dist)
    assert int(r["quantity"]) == expect


def test_no_duplicate_signal_same_day(s: GapFadeStrategy) -> None:
    d1 = _d(2026, 4, 17, 9, 30)
    s._prev_close["META"] = 100.0
    b1 = _bar(ts=d1, open_=101.0, high=101.2, low=99.0, close=99.5)
    r1 = s.on_bar("META", b1)
    assert r1 is not None
    d2 = _d(2026, 4, 17, 9, 45)
    b2 = _bar(ts=d2, open_=99.4, high=100, low=99, close=99.6)
    r2 = s.on_bar("META", b2)
    assert r2 is None


def test_new_session_prev_close(s: GapFadeStrategy) -> None:
    d1 = _d(2026, 4, 16, 16, 0)
    s.on_bar("AAPL", _bar(ts=d1, open_=100, high=101, low=99, close=100.0))
    d2 = _d(2026, 4, 17, 9, 30)
    s._vix_today = 17.0
    b = _bar(ts=d2, open_=101.0, high=101.2, low=99.0, close=99.5)
    r = s.on_bar("AAPL", b)
    assert r is not None
    assert s._prev_close.get("AAPL") == 100.0


def test_vix_unavailable_fail_safe(s: GapFadeStrategy) -> None:
    s._vix_today = None
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["MSFT"] = 100.0
    b = _bar(ts=d, open_=101.0, high=101.2, low=99.0, close=99.5)
    r = s.on_bar("MSFT", b)
    assert r is None


def test_gap_on_bar_vix_zero_fail_safe(s: GapFadeStrategy) -> None:
    """Stale or forced VIX=0 on session is treated like missing data (no entry)."""
    s._vix_today = 0.0
    d = _d(2026, 4, 17, 9, 30)
    s._prev_close["TSLA"] = 100.0
    b = _bar(ts=d, open_=101.0, high=101.2, low=99.0, close=99.5)
    r = s.on_bar("TSLA", b)
    assert r is None


@pytest.mark.asyncio
async def test_prefetch_vix_zero_fail_safe() -> None:
    g = GapFadeStrategy()

    class _Ad:
        async def fetch_barcharts_rest(self, sym: str, tid: str, **_: object) -> list[dict]:
            return [{"Close": 0.0}]

    g.set_broker_context(_Ad(), "t1")
    bar = _bar(ts=_d(2026, 4, 17, 9, 30), open_=100, high=101, low=99, close=99.5)
    await g.prefetch_session_data_async(bar)
    assert g._vix_today is None


@pytest.mark.asyncio
async def test_prefetch_vix_17_5_used() -> None:
    g = GapFadeStrategy()

    class _Ad:
        async def fetch_barcharts_rest(self, sym: str, tid: str, **_: object) -> list[dict]:
            return [{"Close": 17.5}]

    g.set_broker_context(_Ad(), "t1")
    bar = _bar(ts=_d(2026, 4, 17, 9, 30), open_=100, high=101, low=99, close=99.5)
    await g.prefetch_session_data_async(bar)
    assert g._vix_today == 17.5


@pytest.mark.asyncio
async def test_prefetch_vix_async_uses_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    g = GapFadeStrategy()

    class _Ad:
        async def fetch_barcharts_rest(self, sym: str, tid: str, **_: object) -> list[dict]:
            assert "VIX" in sym.upper()
            return [{"Close": "18.5"}]

    g.set_broker_context(_Ad(), "t1")
    bar = _bar(ts=_d(2026, 4, 17, 9, 30), open_=100, high=101, low=99, close=99.5)
    await g.prefetch_session_data_async(bar)
    assert g._vix_today == 18.5

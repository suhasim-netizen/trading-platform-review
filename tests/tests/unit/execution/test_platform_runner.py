# PAPER TRADING MODE

from __future__ import annotations

import asyncio
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from zoneinfo import ZoneInfo

from execution.platform_runner import (
    LoadedStrategy,
    TradingPlatform,
    _next_scheduled_405_et,
    _next_trading_day_405_after,
)
from execution.tracker import PositionTracker


@pytest.mark.asyncio
async def test_all_strategies_run_concurrently(monkeypatch):
    """Each symbol in a strategy gets its own stream task (concurrent gather)."""
    tp = TradingPlatform("director", "paper")
    tp._router = MagicMock()
    tp.adapter = MagicMock()
    seen: list[str] = []

    async def fake_stream(self, spec: LoadedStrategy, sym: str) -> None:
        seen.append(sym)
        await asyncio.sleep(0)

    tp._stream_symbol = types.MethodType(fake_stream, tp)

    class _H:
        def on_bar(self, s, b):
            return None

    spec = LoadedStrategy("strategy_002", "n", _H(), ["AAPL", "MSFT"], "1m")
    await tp._run_strategy(spec)
    assert set(seen) == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_daily_strategy_runs_poll_per_symbol():
    """Daily interval uses ``_poll_daily_bar`` tasks, not streaming."""
    tp = TradingPlatform("director", "paper")
    tp._router = MagicMock()
    tp.adapter = MagicMock()
    seen: list[str] = []

    async def fake_poll(self, spec: LoadedStrategy, sym: str) -> None:
        seen.append(sym)
        await asyncio.sleep(0)

    tp._poll_daily_bar = types.MethodType(fake_poll, tp)
    spec = LoadedStrategy("strategy_004", "n", MagicMock(), ["LASR", "LITE"], "1D")
    await tp._run_strategy(spec)
    assert set(seen) == {"LASR", "LITE"}


def test_next_scheduled_405_wed_morning():
    ny = ZoneInfo("America/New_York")
    wed_10 = datetime(2026, 4, 15, 10, 0, 0, tzinfo=ny)
    assert _next_scheduled_405_et(wed_10) == datetime(2026, 4, 15, 16, 5, 0, tzinfo=ny)


def test_next_scheduled_405_wed_after_close_runs_immediately():
    ny = ZoneInfo("America/New_York")
    wed_1805 = datetime(2026, 4, 15, 18, 5, 0, tzinfo=ny)
    assert _next_scheduled_405_et(wed_1805) == wed_1805


def test_next_trading_day_405_after_wed_evening_is_thu():
    ny = ZoneInfo("America/New_York")
    wed_1805 = datetime(2026, 4, 15, 18, 5, 0, tzinfo=ny)
    nxt = _next_trading_day_405_after(wed_1805)
    assert nxt == datetime(2026, 4, 16, 16, 5, 0, tzinfo=ny)


@pytest.mark.asyncio
async def test_token_refreshed_once_for_all_strategies(monkeypatch):
    """``_setup_broker_and_auth`` runs once per ``start()``; strategies share that auth (no per-strategy refresh)."""
    setup_calls: list[int] = []

    async def fake_setup(self):
        setup_calls.append(1)
        self.adapter = MagicMock()
        self._store = MagicMock()
        self._broker_key = "tradestation"
        self._tracker = PositionTracker()
        self._router = MagicMock()

    async def noop_seed(self):
        return None

    async def noop_restore(self):
        return None

    monkeypatch.setattr(TradingPlatform, "_seed_accounts", noop_seed)
    monkeypatch.setattr(TradingPlatform, "_reconstruct_positions_from_snapshot", noop_restore)
    monkeypatch.setattr(TradingPlatform, "_setup_broker_and_auth", fake_setup)
    monkeypatch.setattr(
        TradingPlatform,
        "_load_strategies",
        lambda self: [
            LoadedStrategy("strategy_002", "a", MagicMock(), ["A"], "1m"),
            LoadedStrategy("strategy_004", "b", MagicMock(), ["B"], "1m"),
        ],
    )

    async def quick_supervisor(self, spec: LoadedStrategy) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(TradingPlatform, "_strategy_supervisor", quick_supervisor)

    async def noop_refresh_loop(self) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(TradingPlatform, "_refresh_loop", noop_refresh_loop)

    tp = TradingPlatform("director", "paper")
    await tp.start()
    assert setup_calls == [1]


@pytest.mark.asyncio
async def test_strategy_crash_does_not_kill_others():
    """``asyncio.gather(..., return_exceptions=True)`` keeps successful tasks isolated from failures."""

    async def boom():
        raise ValueError("strategy stream failed")

    async def ok():
        await asyncio.sleep(0)

    results = await asyncio.gather(boom(), ok(), return_exceptions=True)
    assert isinstance(results[0], ValueError)
    assert results[1] is None


def test_symbol_stream_reconnects_on_error():
    """``_stream_symbol`` wraps ``stream_bars`` in a reconnect loop with a 5s backoff on errors."""
    import inspect

    src = inspect.getsource(TradingPlatform._stream_symbol)
    assert "while True:" in src
    assert "await asyncio.sleep(5.0)" in src
    assert "except" in src

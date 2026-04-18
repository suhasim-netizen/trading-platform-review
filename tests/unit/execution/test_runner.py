# PAPER TRADING MODE

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from brokers.models import Bar
from execution.models import Signal, SignalType
from execution.runner import StrategyRunner
from strategies.base import StrategyMeta, StrategyOwnerKind
from strategies.registry import register


class _Sub:
    def __init__(self, msgs: list[str]) -> None:
        self._msgs = msgs

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        for m in self._msgs:
            yield m


class _Router:
    def __init__(self) -> None:
        self.seen: list[Signal] = []

    async def route(self, signal: Signal):  # type: ignore[no-untyped-def]
        self.seen.append(signal)
        return None


@pytest.mark.asyncio
async def test_runner_drops_tenant_mismatch_bar(monkeypatch):
    register(
        StrategyMeta(
            strategy_id="s1",
            name="S1",
            owner_kind=StrategyOwnerKind.PLATFORM,
            owner_id="director",
            params={"x": 1},
        )
    )

    now = datetime.now(UTC)
    good = Bar(
        tenant_id="tenant_a",
        symbol="AAPL",
        interval="1d",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        bar_start=now,
        bar_end=now + timedelta(days=1),
    )
    bad = good.model_copy(update={"tenant_id": "tenant_b"})
    msgs = [json.dumps(bad.model_dump(mode="json")), json.dumps(good.model_dump(mode="json"))]

    router = _Router()

    def _sig(bar: Bar, meta):  # type: ignore[no-untyped-def]
        return [
            Signal(
                tenant_id=bar.tenant_id,
                trading_mode="paper",
                strategy_id="s1",
                symbol=bar.symbol,
                signal_type=SignalType.ENTER,
            )
        ]

    runner = StrategyRunner(
        tenant_id="tenant_a",
        trading_mode="paper",
        strategy_id="s1",
        symbol="AAPL",
        interval="1d",
        subscriber=_Sub(msgs),
        router=router,  # type: ignore[arg-type]
        signal_fn=_sig,
    )
    await runner.run(max_bars=2)

    assert len(router.seen) == 1
    assert router.seen[0].tenant_id == "tenant_a"


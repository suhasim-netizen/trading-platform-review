"""Market data pipeline — mocked streams, tenant isolation on Redis channels."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from brokers.base import BrokerAdapter
from brokers.models import AuthToken, Bar, BrokerCredentials, CancelReceipt, Order, OrderReceipt, Quote
from data.pipeline import MarketDataPipeline
from tenancy.redis_keys import bars_channel


class _MinimalAdapter(BrokerAdapter):
    """Test double: only ``stream_bars`` is real; other methods are stubs."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def authenticate(self, credentials: BrokerCredentials) -> AuthToken:
        raise NotImplementedError

    async def refresh_token(self, token: AuthToken) -> AuthToken:
        raise NotImplementedError

    async def get_quote(self, symbol: str, tenant_id: str) -> Quote:
        raise NotImplementedError

    async def get_account(self, account_id: str, tenant_id: str):
        raise NotImplementedError

    async def place_order(self, order: Order, *, tenant_id: str, account_id: str) -> OrderReceipt:
        raise NotImplementedError

    async def cancel_order(self, order_id: str, tenant_id: str) -> CancelReceipt:
        raise NotImplementedError

    async def get_positions(self, account_id: str, tenant_id: str):
        raise NotImplementedError

    def stream_quotes(self, symbols: list[str], tenant_id: str):
        raise NotImplementedError

    def stream_bars(self, symbol: str, interval: str, tenant_id: str):
        wanted = (symbol.strip(), interval.strip(), tenant_id)

        async def _gen():
            for b in self._bars:
                if (b.symbol.strip(), b.interval.strip(), b.tenant_id) == wanted:
                    yield b

        return _gen()

    def stream_order_updates(self, account_id: str, tenant_id: str):
        raise NotImplementedError


def _bar(*, tenant_id: str, symbol: str, interval: str, start: datetime, close: Decimal = Decimal("100")) -> Bar:
    return Bar(
        tenant_id=tenant_id,
        symbol=symbol,
        interval=interval,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=close,
        volume=Decimal("1000"),
        bar_start=start,
        raw={},
    )


@pytest.mark.asyncio
async def test_pipeline_publishes_normalized_bar_to_tenant_channel():
    t0 = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    bar = _bar(tenant_id="tenant_a", symbol="MSFT", interval="5m", start=t0)
    adapter = _MinimalAdapter([bar])
    redis = AsyncMock()
    pipe = MarketDataPipeline(
        adapter,
        redis=redis,
        tenant_id="tenant_a",
        symbol="MSFT",
        interval="5m",
    )
    await pipe.run(max_bars=1)
    ch = bars_channel("tenant_a", "MSFT", "5m")
    redis.publish.assert_awaited_once()
    call_kw = redis.publish.await_args
    assert call_kw[0][0] == ch
    assert "MSFT" in call_kw[0][1]
    assert "tenant_a" in call_kw[0][1]


@pytest.mark.asyncio
async def test_two_tenant_isolation_redis_channels():
    """Tenant A's stream must only publish to tenant A's Redis channel (never B's)."""
    t0 = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    bars = [
        _bar(tenant_id="tenant_a", symbol="AAPL", interval="1m", start=t0, close=Decimal("150")),
        _bar(tenant_id="tenant_b", symbol="AAPL", interval="1m", start=t0, close=Decimal("160")),
    ]
    adapter = _MinimalAdapter(bars)
    redis = AsyncMock()

    pa = MarketDataPipeline(
        adapter,
        redis=redis,
        tenant_id="tenant_a",
        symbol="AAPL",
        interval="1m",
    )
    await pa.run(max_bars=1)

    pb = MarketDataPipeline(
        adapter,
        redis=redis,
        tenant_id="tenant_b",
        symbol="AAPL",
        interval="1m",
    )
    await pb.run(max_bars=1)

    ch_a = bars_channel("tenant_a", "AAPL", "1m")
    ch_b = bars_channel("tenant_b", "AAPL", "1m")
    assert ch_a != ch_b
    assert ch_a.startswith("tenant_a:")
    assert ch_b.startswith("tenant_b:")

    channels = [c.args[0] for c in redis.publish.await_args_list]
    assert channels == [ch_a, ch_b]
    p0, p1 = redis.publish.await_args_list[0].args[1], redis.publish.await_args_list[1].args[1]
    assert '"tenant_id":"tenant_a"' in p0 and '"tenant_id":"tenant_b"' not in p0
    assert '"tenant_id":"tenant_b"' in p1 and '"tenant_id":"tenant_a"' not in p1

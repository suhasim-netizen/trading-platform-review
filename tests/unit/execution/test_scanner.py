# PAPER TRADING MODE

"""Multi-symbol scanner — concurrent streams and handler dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from brokers.base import BrokerAdapter
from brokers.models import AuthToken, Bar, BrokerCredentials, CancelReceipt, Order, OrderReceipt, Quote
from execution.scanner import MultiSymbolScanner


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


class _PerSymbolStreamAdapter(BrokerAdapter):
    """Yields pre-baked bars per symbol (``stream_bars`` only)."""

    def __init__(self, bars_by_symbol: dict[str, list[Bar]]) -> None:
        self._bars_by_symbol = bars_by_symbol

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
        wanted_sym = symbol.strip()
        wanted_iv = interval.strip()

        async def _gen():
            for b in self._bars_by_symbol.get(wanted_sym, []):
                if b.interval.strip() == wanted_iv and b.tenant_id == tenant_id:
                    yield b

        return _gen()

    def stream_order_updates(self, account_id: str, tenant_id: str):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_multi_symbol_subscription():
    t0 = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)
    ad = _PerSymbolStreamAdapter(
        {
            "AVGO": [_bar(tenant_id="t1", symbol="AVGO", interval="5m", start=t0)],
            "MU": [_bar(tenant_id="t1", symbol="MU", interval="5m", start=t0)],
        }
    )
    sc = MultiSymbolScanner("t1", ad)
    await sc.subscribe(["AVGO", "MU"], interval="5min")
    assert sc.symbols == ("AVGO", "MU")
    assert sc.interval == "5m"


@pytest.mark.asyncio
async def test_concurrent_bar_processing():
    t0 = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)
    bars_a = [
        _bar(tenant_id="t1", symbol="A", interval="5m", start=t0, close=Decimal("1")),
        _bar(tenant_id="t1", symbol="A", interval="5m", start=t0, close=Decimal("2")),
    ]
    bars_b = [
        _bar(tenant_id="t1", symbol="B", interval="5m", start=t0, close=Decimal("3")),
        _bar(tenant_id="t1", symbol="B", interval="5m", start=t0, close=Decimal("4")),
    ]
    ad = _PerSymbolStreamAdapter({"A": bars_a, "B": bars_b})
    sc = MultiSymbolScanner("t1", ad)
    await sc.subscribe(["A", "B"], interval="5m")
    seen: list[Decimal] = []

    async def on_a(bar: Bar) -> None:
        seen.append(bar.close)

    async def on_b(bar: Bar) -> None:
        seen.append(bar.close)

    await sc.run({"A": on_a, "B": on_b}, max_bars=4)
    assert sorted(seen) == sorted([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")])


@pytest.mark.asyncio
async def test_signal_handler_dispatch():
    t0 = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)
    ad = _PerSymbolStreamAdapter(
        {
            "AVGO": [_bar(tenant_id="t1", symbol="AVGO", interval="5m", start=t0)],
            "MU": [_bar(tenant_id="t1", symbol="MU", interval="5m", start=t0)],
        }
    )
    sc = MultiSymbolScanner("t1", ad)
    await sc.subscribe(["AVGO", "MU"], interval="5m")
    routes: list[str] = []

    def on_avgo(bar: Bar) -> None:
        routes.append(f"avgo:{bar.symbol}")

    def on_mu(bar: Bar) -> None:
        routes.append(f"mu:{bar.symbol}")

    await sc.run({"AVGO": on_avgo, "MU": on_mu}, max_bars=2)
    assert sorted(routes) == ["avgo:AVGO", "mu:MU"]

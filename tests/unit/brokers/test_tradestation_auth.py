# DRAFT — Pending Security Architect sign-off (P1-03)

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from brokers.exceptions import BrokerAuthError, BrokerNetworkError, BrokerValidationError
from brokers.models import AuthToken, InstrumentType, Order, OrderSide, OrderStatus, OrderType
from brokers.tradestation.adapter import (
    TradeStationAdapter,
    _bar_from_stream_obj,
    _marketdata_path_symbol,
)
from brokers.tradestation.auth import exchange_authorization_code, refresh_access_token


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload == "__MALFORMED__":
            raise ValueError("bad json")
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse | None = None, *, raise_err: Exception | None = None) -> None:
        self._response = response
        self._raise_err = raise_err

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data=None, headers=None):
        if self._raise_err is not None:
            raise self._raise_err
        assert self._response is not None
        return self._response


@pytest.mark.asyncio
async def test_exchange_success(monkeypatch):
    resp = _FakeResponse(
        200,
        {
            "access_token": "ACCESS",
            "refresh_token": "REFRESH",
            "token_type": "Bearer",
            "expires_in": 60,
            "scope": "MarketData",
        },
    )

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(resp))

    tok = await exchange_authorization_code(
        tenant_id="tenant_a",
        authorization_code="CODE",
        client_id="CID",
        client_secret="CSEC",
        redirect_uri="https://localhost/callback",
        token_url="https://localhost/oauth/token",
        timeout_s=5.0,
    )
    assert tok.tenant_id == "tenant_a"
    assert tok.access_token == "ACCESS"
    assert tok.refresh_token == "REFRESH"
    assert tok.expires_at is not None


@pytest.mark.asyncio
async def test_exchange_401_maps_to_auth_error(monkeypatch):
    resp = _FakeResponse(401, {"error": "unauthorized"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(resp))

    with pytest.raises(BrokerAuthError):
        await exchange_authorization_code(
            tenant_id="tenant_a",
            authorization_code="CODE",
            client_id="CID",
            client_secret="CSEC",
            redirect_uri="https://localhost/callback",
            token_url="https://localhost/oauth/token",
        )


@pytest.mark.asyncio
async def test_network_error_maps_to_broker_network_error(monkeypatch):
    req = httpx.Request("POST", "https://localhost/oauth/token")
    err = httpx.ConnectError("boom", request=req)
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(raise_err=err))

    with pytest.raises(BrokerNetworkError):
        await exchange_authorization_code(
            tenant_id="tenant_a",
            authorization_code="CODE",
            client_id="CID",
            client_secret="CSEC",
            redirect_uri="https://localhost/callback",
            token_url="https://localhost/oauth/token",
        )


@pytest.mark.asyncio
async def test_malformed_json_maps_to_validation_error(monkeypatch):
    resp = _FakeResponse(200, "__MALFORMED__")
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(resp))

    with pytest.raises(BrokerValidationError):
        await exchange_authorization_code(
            tenant_id="tenant_a",
            authorization_code="CODE",
            client_id="CID",
            client_secret="CSEC",
            redirect_uri="https://localhost/callback",
            token_url="https://localhost/oauth/token",
        )


@pytest.mark.asyncio
async def test_refresh_success(monkeypatch):
    resp = _FakeResponse(
        200,
        {
            "access_token": "ACCESS2",
            "refresh_token": "REFRESH2",
            "token_type": "Bearer",
            "expires_in": 120,
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(resp))

    tok = await refresh_access_token(
        tenant_id="tenant_a",
        refresh_token="REFRESH",
        client_id="CID",
        client_secret="CSEC",
        token_url="https://localhost/oauth/token",
    )
    assert tok.tenant_id == "tenant_a"
    assert tok.access_token == "ACCESS2"
    assert tok.refresh_token == "REFRESH2"


# --- TradeStationAdapter REST / stream (mocked httpx) ---


@pytest.fixture
def ts_session_token() -> AuthToken:
    return AuthToken(
        tenant_id="tenant_a",
        access_token="ACCESS",
        refresh_token="REFR",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.fixture
def ts_adapter(ts_session_token: AuthToken) -> TradeStationAdapter:
    store = MagicMock()
    store.get_auth_token.return_value = ts_session_token
    audit = MagicMock()
    return TradeStationAdapter(
        store=store,
        audit=audit,
        api_base_url="https://example.test",
        market_data_base_url="https://api.tradestation.com",
        ws_base_url="wss://example.test",
        client_id="cid",
        client_secret="csec",
        account_id="SIM123",
        paper_trading_mode=False,
    )


def test_live_order_url_rejected_in_paper_mode() -> None:
    """Paper mode: order execution must use sim; live market data URL is allowed."""
    with pytest.raises(BrokerValidationError, match="PAPER_TRADING_MODE"):
        TradeStationAdapter(
            paper_trading_mode=True,
            api_base_url="https://api.tradestation.com",
            market_data_base_url="https://api.tradestation.com",
            ws_base_url="wss://api.tradestation.com",
        )


def test_paper_mode_allows_live_market_data_when_orders_use_sim() -> None:
    TradeStationAdapter(
        paper_trading_mode=True,
        api_base_url="https://sim.api.tradestation.com",
        market_data_base_url="https://api.tradestation.com",
        ws_base_url="wss://sim.api.tradestation.com",
    )


def test_marketdata_path_symbol_futures_front_month() -> None:
    assert _marketdata_path_symbol("@ES") == "ESM26"
    assert _marketdata_path_symbol("@NQ") == "NQM26"
    assert _marketdata_path_symbol("@MES") == "MESM26"
    assert _marketdata_path_symbol("@MNQ") == "MNQM26"
    assert _marketdata_path_symbol("AAPL") == "AAPL"


def test_bar_from_stream_uses_symbol_for_bar_override() -> None:
    obj = {
        "Symbol": "NQM26",
        "Open": "1",
        "High": "2",
        "Low": "0.5",
        "Close": "1.5",
        "TimeStamp": "2026-04-16T18:30:00+00:00",
        "TotalVolume": "100",
    }
    b = _bar_from_stream_obj(obj, "t1", "@NQ", "1m", symbol_for_bar="@NQ")
    assert b is not None
    assert b.symbol == "@NQ"


class _HttpResp:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8") if payload is not None else b"{}"

    def json(self) -> object:
        return self._payload


class _HttpClient:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code

    async def __aenter__(self) -> _HttpClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def request(self, method: str, url: str, headers=None, json=None) -> _HttpResp:
        return _HttpResp(self._status_code, self._payload)

    def stream(self, method: str, url: str, headers=None) -> object:
        raise RuntimeError("stream not used")


class _StreamBody:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    async def aiter_text(self):
        yield '{"Symbol":"IBM","Last":"101.25","Bid":"101.0","Ask":"101.5"}\n'


class _StreamCtx:
    def __init__(self, body: _StreamBody) -> None:
        self._body = body

    async def __aenter__(self) -> _StreamBody:
        return self._body

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _StreamClient:
    def __init__(self, body: _StreamBody) -> None:
        self._body = body

    async def __aenter__(self) -> _StreamClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def request(self, *a, **k) -> _HttpResp:
        raise RuntimeError("request not used")

    def stream(self, method: str, url: str, headers=None) -> _StreamCtx:
        return _StreamCtx(self._body)


@pytest.mark.asyncio
async def test_adapter_get_quote(monkeypatch, ts_adapter: TradeStationAdapter):
    payload = {"Quotes": [{"Symbol": "SPY", "Bid": "400.1", "Ask": "400.2", "Last": "400.15"}]}
    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _HttpClient(payload),
    )
    q = await ts_adapter.get_quote("SPY", "tenant_a")
    assert q.tenant_id == "tenant_a"
    assert q.symbol == "SPY"
    assert q.last is not None


@pytest.mark.asyncio
async def test_adapter_get_account(monkeypatch, ts_adapter: TradeStationAdapter):
    payload = {"AccountID": "SIM123", "AccountName": "Paper", "CashBalance": "1000.00"}
    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _HttpClient(payload),
    )
    a = await ts_adapter.get_account("SIM123", "tenant_a")
    assert a.account_id == "SIM123"
    assert a.tenant_id == "tenant_a"


@pytest.mark.asyncio
async def test_adapter_place_order(monkeypatch, ts_adapter: TradeStationAdapter):
    payload = {"OrderID": "ord-1", "Status": "OPN"}
    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _HttpClient(payload),
    )
    o = Order(symbol="SPY", side=OrderSide.BUY, quantity=1, order_type=OrderType.MARKET)
    rec = await ts_adapter.place_order(o, tenant_id="tenant_a", account_id="SIM123")
    assert rec.order_id == "ord-1"
    assert rec.tenant_id == "tenant_a"
    assert rec.status == OrderStatus.SUBMITTED


@pytest.mark.asyncio
async def test_adapter_place_order_futures_contract_and_asset_type(monkeypatch, ts_adapter: TradeStationAdapter):
    captured: dict[str, Any] = {}

    class _CapClient:
        async def __aenter__(self) -> _CapClient:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def request(self, method: str, url: str, headers=None, json=None) -> _HttpResp:
            captured["method"] = method
            captured["json"] = json
            return _HttpResp(200, {"OrderID": "ord-f1", "Status": "OPN"})

    monkeypatch.setattr("brokers.tradestation.adapter.httpx.AsyncClient", lambda **kwargs: _CapClient())
    o = Order(
        symbol="@ES",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        instrument_type=InstrumentType.FUTURES,
    )
    rec = await ts_adapter.place_order(o, tenant_id="tenant_a", account_id="SIM3236524F")
    assert rec.order_id == "ord-f1"
    body = captured.get("json") or {}
    assert body.get("Symbol") == "ESM26"
    assert body.get("AssetType") == "FUTURE"
    assert body.get("AccountID") == "SIM3236524F"


@pytest.mark.asyncio
async def test_adapter_cancel_order(monkeypatch, ts_adapter: TradeStationAdapter):
    class _DelResp:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = b""

    class _DelClient:
        async def __aenter__(self) -> _DelClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def delete(self, url: str, headers=None) -> _DelResp:
            return _DelResp()

        async def request(self, *a, **k) -> object:
            raise RuntimeError("unused")

        async def stream(self, *a, **k) -> object:
            raise RuntimeError("unused")

    monkeypatch.setattr("brokers.tradestation.adapter.httpx.AsyncClient", lambda **kwargs: _DelClient())
    cr = await ts_adapter.cancel_order("ord-9", "tenant_a")
    assert cr.cancelled is True
    assert cr.order_id == "ord-9"


@pytest.mark.asyncio
async def test_adapter_get_positions(monkeypatch, ts_adapter: TradeStationAdapter):
    payload = {
        "Positions": [
            {"Symbol": "SPY", "Quantity": "10", "AveragePrice": "400", "MarketValue": "4000"},
        ]
    }
    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _HttpClient(payload),
    )
    pos = await ts_adapter.get_positions("SIM123", "tenant_a")
    assert len(pos) == 1
    assert pos[0].symbol == "SPY"
    assert pos[0].tenant_id == "tenant_a"


@pytest.mark.asyncio
async def test_adapter_stream_quotes(monkeypatch, ts_adapter: TradeStationAdapter):
    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _StreamClient(_StreamBody()),
    )
    gen = ts_adapter.stream_quotes(["IBM"], "tenant_a")
    out = await gen.__anext__()
    assert out.symbol == "IBM"
    assert out.tenant_id == "tenant_a"


@pytest.mark.asyncio
async def test_adapter_stream_order_updates(monkeypatch, ts_adapter: TradeStationAdapter):
    class _OrdStream(_StreamBody):
        async def aiter_text(self):
            yield '{"OrderID":"o-1","Status":"FLL","AccountID":"SIM123"}\n'

    monkeypatch.setattr(
        "brokers.tradestation.adapter.httpx.AsyncClient",
        lambda **kwargs: _StreamClient(_OrdStream()),
    )
    gen = ts_adapter.stream_order_updates("SIM123", "tenant_a")
    ou = await gen.__anext__()
    assert ou.order_id == "o-1"
    assert ou.status == OrderStatus.FILLED


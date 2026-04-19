# PAPER_TRADING_MODE=True: order execution URLs must be sim; market data may use the live API.

"""TradeStation REST + HTTP streaming adapter (API v3 paths).

OAuth (authenticate / refresh_token) plus market data, execution, and brokerage streams.
Streaming uses chunked HTTP responses (``application/vnd.tradestation.streams.*+json``), not raw WebSocket frames.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from brokers.base import BrokerAdapter
from brokers.exceptions import (
    BrokerAuthError,
    BrokerError,
    BrokerNetworkError,
    BrokerRateLimitError,
    BrokerValidationError,
)
from brokers.models import (
    Account,
    AuthToken,
    Bar,
    BrokerCredentials,
    CancelReceipt,
    InstrumentType,
    Order,
    OrderReceipt,
    OrderSide,
    OrderStatus,
    OrderType,
    OrderUpdate,
    Position,
    Quote,
    TimeInForce,
)

from security.crypto import decrypt_secret
from services.audit_log import AuditLogger
from services.broker_credentials_store import BrokerCredentialsStore

from .auth import exchange_authorization_code, refresh_access_token

# Defaults when constructor URLs are omitted.
_PAPER_ORDER_BASE = "https://sim.api.tradestation.com"
_LIVE_MARKET_DATA_BASE = "https://api.tradestation.com"
# Host substring required for order execution bases when paper-trading enforcement is on.
_SIM_API_HOST = "sim.api.tradestation.com"

# Front-month futures roots for market-data paths (root → contract as of roll calendar).
# TODO: Auto-resolve front month from TradeStation symbol lookup API before each quarterly roll.
# Next roll date: June 20, 2026 → switch to U26 (Sep) contracts after roll.
FUTURES_FRONT_MONTH: dict[str, str] = {
    "ES": "ESM26",  # E-mini S&P 500 June 2026
    "NQ": "NQM26",  # E-mini Nasdaq June 2026
    "MES": "MESM26",  # Micro E-mini S&P 500
    "MNQ": "MNQM26",  # Micro E-mini Nasdaq
}


def _resolve_paper_trading_mode(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    from config import get_settings

    return get_settings().paper_trading_mode


def _marketdata_path_symbol(symbol: str) -> str:
    """Convert strategy symbol to API path symbol.

    - Strips ``@`` prefix: ``@ES`` → ``ES``, ``@NQ`` → ``NQ``.
    - Resolves listed futures roots to front-month contract (e.g. ``NQ`` → ``NQM26``).
    - Equities unchanged: ``AVGO`` → ``AVGO``.

    ``Bar`` objects still use the original strategy symbol (see ``symbol_for_bar`` in
    ``stream_bars`` / ``_bar_from_stream_obj``).
    """
    s = symbol.strip().lstrip("@").upper()
    return FUTURES_FRONT_MONTH.get(s, s)


def _as_str(v: object | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        vv = v.strip()
        return vv if vv else None
    return None


def _to_decimal(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _map_http_exception(status_code: int) -> BrokerError:
    if status_code in (401, 403):
        return BrokerAuthError("request rejected")
    if status_code == 429:
        return BrokerRateLimitError("rate limited")
    if status_code >= 500:
        return BrokerNetworkError("broker service error")
    return BrokerValidationError("request failed")


def _ts_order_type(ot: OrderType) -> str:
    return {
        OrderType.MARKET: "Market",
        OrderType.LIMIT: "Limit",
        OrderType.STOP: "StopMarket",
        OrderType.STOP_LIMIT: "StopLimit",
    }[ot]


def _ts_tif_duration(tif: TimeInForce) -> str:
    return {
        TimeInForce.DAY: "DAY",
        TimeInForce.GTC: "GTC",
        TimeInForce.IOC: "IOC",
        TimeInForce.FOK: "FOK",
    }[tif]


def _map_ts_order_status(raw: object) -> OrderStatus:
    s = str(raw or "").strip().upper()
    if not s:
        return OrderStatus.SUBMITTED
    if any(x in s for x in ("FILL", "FLL")):
        return OrderStatus.FILLED
    if "PART" in s or "PARTIAL" in s:
        return OrderStatus.PARTIALLY_FILLED
    if any(x in s for x in ("CANCEL", "OUT")):
        return OrderStatus.CANCELLED
    if "REJ" in s or "REJECT" in s:
        return OrderStatus.REJECTED
    if "EXP" in s:
        return OrderStatus.EXPIRED
    if any(x in s for x in ("NEW", "ACK", "OPN", "OPEN", "WORK", "ROUT")):
        return OrderStatus.SUBMITTED
    return OrderStatus.NEW


class TradeStationAdapter(BrokerAdapter):
    """Concrete adapter for TradeStation API v3 (paper/simulation defaults)."""

    BROKER_NAME = "tradestation"

    def __init__(
        self,
        *,
        store: BrokerCredentialsStore | None = None,
        audit: AuditLogger | None = None,
        token_url: str | None = None,
        auth_base_url: str | None = None,
        api_base_url: str | None = None,
        market_data_base_url: str | None = None,
        ws_base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        client_secret_enc: str | None = None,
        redirect_uri: str | None = None,
        trading_mode: str = "paper",
        account_id: str = "",
        http_timeout_s: float = 30.0,
        stream_idle_timeout_s: float | None = 300.0,
        stream_reconnect_s: float = 900.0,
        paper_trading_mode: bool | None = None,
        **_: Any,
    ) -> None:
        self._store = store
        self._audit = audit
        self._paper_trading_mode = _resolve_paper_trading_mode(paper_trading_mode)
        self._token_url = token_url
        if not self._token_url and auth_base_url:
            self._token_url = auth_base_url.rstrip("/") + "/oauth/token"
        # Order execution + brokerage REST (paper → sim, live → api.tradestation.com).
        self._order_api_url = (api_base_url or "").strip() or _PAPER_ORDER_BASE
        # Market data REST + bar/quote streams (typically live API).
        self._market_data_url = (market_data_base_url or "").strip() or _LIVE_MARKET_DATA_BASE
        # Quote/bar streams use the market-data host; order updates stream uses the order host + ws_base_url.
        self._market_stream_base_url = _http_base_from_ws_or_api(None, self._market_data_url)
        self._order_stream_base_url = _http_base_from_ws_or_api(ws_base_url, self._order_api_url)
        if self._paper_trading_mode:
            self._check_paper_mode_guard(self._order_api_url)
            self._check_paper_mode_guard(self._order_stream_base_url)
        self._client_id = client_id
        self._client_secret_plain = client_secret or (
            decrypt_secret(client_secret_enc) if client_secret_enc else None
        )
        self._client_secret_enc = client_secret_enc
        self._redirect_uri = redirect_uri
        self._trading_mode = trading_mode
        self._account_id = account_id
        self._http_timeout_s = http_timeout_s
        self._stream_idle_timeout_s = stream_idle_timeout_s
        self._stream_reconnect_s = stream_reconnect_s
        # Set by barchart stream when broker returns e.g. InvalidSymbol (read by platform_runner backoff).
        self._last_barchart_stream_error: str | None = None
        # Serialize OAuth refresh so concurrent streams/requests do not stampede TradeStation.
        self._refresh_lock: asyncio.Lock | None = None

    def _check_paper_mode_guard(self, url: str) -> None:
        """Only applies to order execution HTTP/stream bases (not market data)."""
        if not self._paper_trading_mode:
            return
        if _SIM_API_HOST not in url.lower():
            raise BrokerValidationError(
                "PAPER_TRADING_MODE=True: order execution must use sim.api.tradestation.com"
            )

    @property
    def market_data_url(self) -> str:
        """Live market data REST/stream base (quotes, barcharts, bar streams)."""
        return self._market_data_url

    @property
    def order_api_url(self) -> str:
        """Order execution + brokerage REST/sim or live."""
        return self._order_api_url

    async def authenticate(self, credentials: BrokerCredentials) -> AuthToken:
        if self._store is None or self._audit is None:
            raise BrokerValidationError("token store and audit logger are required for authenticate")
        tenant_id = credentials.tenant_id
        code = _as_str(credentials.authorization_code)
        cid = _as_str(credentials.client_id) or _as_str(self._client_id)
        csec = _as_str(credentials.client_secret) or self._client_secret_plain
        ruri = _as_str(credentials.redirect_uri) or _as_str(self._redirect_uri)
        # OAuth session row is tenant-wide (matches auth_tradestation bootstrap: account_id_default "").
        oauth_account_key = ""

        if not code:
            raise BrokerValidationError("authorization_code is required")
        if not cid or not csec or not ruri:
            raise BrokerValidationError("client_id, client_secret, and redirect_uri are required")

        tok = await exchange_authorization_code(
            tenant_id=tenant_id,
            authorization_code=code,
            client_id=cid,
            client_secret=csec,
            redirect_uri=ruri,
            token_url=self._token_url,
            timeout_s=self._http_timeout_s,
        )

        self._store.upsert_tokens(
            tenant_id=tenant_id,
            trading_mode=self._trading_mode,
            broker_name=self.BROKER_NAME,
            account_id=oauth_account_key,
            token=tok,
        )
        self._audit.write(tenant_id=tenant_id, event_type="auth_succeeded", metadata={"broker": self.BROKER_NAME})
        return tok

    async def refresh_token(self, token: AuthToken) -> AuthToken:
        """Persist new OAuth tokens from ``refresh_token`` grant (with retries).

        Exponential backoff: 2s, 4s, 8s between attempts (including after the final failure).
        """
        if self._store is None or self._audit is None:
            raise BrokerValidationError("token store and audit logger are required for refresh_token")
        tenant_id = token.tenant_id
        if not token.refresh_token:
            raise BrokerValidationError("refresh_token is required")

        cid = _as_str(self._client_id)
        csec = self._client_secret_plain
        if not cid or not csec:
            raise BrokerValidationError("client_id and client_secret must be configured on adapter")

        max_attempts = 3
        last_err: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                refreshed = await asyncio.wait_for(
                    refresh_access_token(
                        tenant_id=tenant_id,
                        refresh_token=token.refresh_token,
                        client_id=cid,
                        client_secret=csec,
                        token_url=self._token_url,
                        timeout_s=self._http_timeout_s,
                    ),
                    timeout=15.0,
                )
                self._store.upsert_tokens(
                    tenant_id=tenant_id,
                    trading_mode=self._trading_mode,
                    broker_name=self.BROKER_NAME,
                    account_id="",
                    token=refreshed,
                )
                self._audit.write(
                    tenant_id=tenant_id, event_type="token_refreshed", metadata={"broker": self.BROKER_NAME}
                )
                print("[ADAPTER] OAuth refresh complete")
                return refreshed
            except BaseException as e:
                last_err = e
                wait = 2**attempt
                print(f"[REFRESH] Attempt {attempt} failed — retrying in {wait}s")
                await asyncio.sleep(float(wait))
        print(f"[REFRESH] All {max_attempts} attempts failed — giving up")
        assert last_err is not None
        raise last_err

    async def _bearer_token(self, tenant_id: str) -> str:
        """Return a valid access token; refresh using stored refresh_token when near expiry."""
        if self._store is None:
            raise BrokerAuthError("broker session store not configured")
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        tok = self._store.get_auth_token(
            tenant_id=tenant_id,
            trading_mode=self._trading_mode,
            broker_name=self.BROKER_NAME,
            account_id="",
        )
        # TradeStation access tokens are short-lived (~20m); refresh with ~10m buffer.
        now = datetime.now(UTC)
        skew = timedelta(minutes=10)
        needs_refresh = bool(tok.refresh_token) and (
            tok.expires_at is not None and now >= tok.expires_at - skew
        )
        if needs_refresh:
            if self._audit is None:
                raise BrokerAuthError("token refresh unavailable")
            async with self._refresh_lock:
                tok = self._store.get_auth_token(
                    tenant_id=tenant_id,
                    trading_mode=self._trading_mode,
                    broker_name=self.BROKER_NAME,
                    account_id="",
                )
                now = datetime.now(UTC)
                needs_refresh = bool(tok.refresh_token) and (
                    tok.expires_at is not None and now >= tok.expires_at - skew
                )
                if needs_refresh:
                    print("[ADAPTER] OAuth access token stale or expiring — refreshing")
                    tok = await self.refresh_token(tok)
        return tok.access_token

    def _auth_headers(self, bearer: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        tenant_id: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        bearer = await self._bearer_token(tenant_id)
        headers = self._auth_headers(bearer)
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout_s) as client:
                resp = await client.request(method, url, headers=headers, json=json_body)
        except httpx.RequestError as e:
            raise BrokerNetworkError("http request failed") from e

        if resp.status_code not in (200, 201):
            print(f"[HTTP_ERR] Status: {resp.status_code}")
            print(f"[HTTP_ERR] URL: {url}")
            print(f"[HTTP_ERR] Body sent: {json_body!r}")
            try:
                print(f"[HTTP_ERR] Response: {resp.text}")
            except Exception:
                pass
            if resp.status_code >= 400:
                raise _map_http_exception(resp.status_code)
            raise BrokerValidationError(f"unexpected HTTP status {resp.status_code}")
        try:
            if resp.content:
                return resp.json()
            return {}
        except ValueError as e:
            raise BrokerValidationError("response not valid json") from e

    async def get_quote(self, symbol: str, tenant_id: str) -> Quote:
        sym = symbol.strip()
        if not sym:
            raise BrokerValidationError("symbol is required")
        url = f"{self._market_data_url.rstrip('/')}/v3/marketdata/quotes/{quote(sym, safe='')}"
        data = await self._request_json("GET", url, tenant_id=tenant_id)
        q = _parse_quote_payload(data, sym, tenant_id)
        if q is None:
            raise BrokerValidationError("quote response missing data")
        return q

    async def get_account(self, account_id: str, tenant_id: str) -> Account:
        aid = account_id.strip()
        if not aid:
            raise BrokerValidationError("account_id is required")
        url = f"{self._order_api_url.rstrip('/')}/v3/brokerage/accounts/{quote(aid, safe='')}"
        data = await self._request_json("GET", url, tenant_id=tenant_id)
        return _parse_account(data, aid, tenant_id)

    async def place_order(self, order: Order, *, tenant_id: str, account_id: str) -> OrderReceipt:
        aid = account_id.strip()
        if not aid:
            raise BrokerValidationError("account_id is required")
        path_symbol = _marketdata_path_symbol(order.symbol)
        trade_action = "BUY" if order.side == OrderSide.BUY else "SELL"
        qty_s = str(int(float(order.quantity)))
        body: dict[str, Any] = {
            "AccountID": aid,
            "Symbol": path_symbol,
            "Quantity": qty_s,
            "OrderType": _ts_order_type(order.order_type),
            "TradeAction": trade_action,
            "TimeInForce": {"Duration": _ts_tif_duration(order.time_in_force)},
        }
        if order.instrument_type in (InstrumentType.FUTURES, InstrumentType.FUTURES_OPTIONS):
            body["AssetType"] = "FUTURE"
        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.limit_price is not None:
            body["LimitPrice"] = f"{float(order.limit_price):.2f}"
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and order.stop_price is not None:
            body["StopPrice"] = f"{float(order.stop_price):.2f}"
        if order.client_order_id:
            body["ClientOrderID"] = order.client_order_id

        url = f"{self._order_api_url.rstrip('/')}/v3/orderexecution/orders"
        data = await self._request_json("POST", url, tenant_id=tenant_id, json_body=body)
        oid, status = _parse_order_submit_response(data)
        if not oid:
            raise BrokerValidationError("order response missing order id")
        orig_sym = order.symbol.strip()
        print(f"[ORDER] {orig_sym} {trade_action} {order.quantity} {path_symbol} → {aid}")
        if status == OrderStatus.FILLED and isinstance(data, dict):
            fp = _to_decimal(
                data.get("AverageFillPrice") or data.get("AvgFillPrice") or data.get("AverageExecutionPrice")
            )
            if fp is not None:
                print(f"[ORDER] Fill received: {path_symbol} @ {fp}")
        return OrderReceipt(order_id=oid, tenant_id=tenant_id, status=status, submitted_at=datetime.now(UTC))

    async def cancel_order(self, order_id: str, tenant_id: str) -> CancelReceipt:
        oid = order_id.strip()
        if not oid:
            raise BrokerValidationError("order_id is required")
        aid = _as_str(self._account_id)
        if not aid:
            raise BrokerValidationError("default account_id must be configured on adapter for cancel")
        url = f"{self._order_api_url.rstrip('/')}/v3/orderexecution/orders/{quote(oid, safe='')}"
        bearer = await self._bearer_token(tenant_id)
        headers = self._auth_headers(bearer)
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout_s) as client:
                resp = await client.delete(url, headers=headers)
        except httpx.RequestError as e:
            raise BrokerNetworkError("http request failed") from e
        if resp.status_code >= 400:
            raise _map_http_exception(resp.status_code)
        return CancelReceipt(order_id=oid, tenant_id=tenant_id, cancelled=True)

    async def get_positions(self, account_id: str, tenant_id: str) -> list[Position]:
        aid = account_id.strip()
        if not aid:
            raise BrokerValidationError("account_id is required")
        url = f"{self._order_api_url.rstrip('/')}/v3/brokerage/accounts/{quote(aid, safe='')}/positions"
        data = await self._request_json("GET", url, tenant_id=tenant_id)
        return _parse_positions(data, aid, tenant_id)

    async def fetch_barcharts_rest(
        self,
        symbol: str,
        tenant_id: str,
        *,
        interval: str = "1",
        unit: str = "Daily",
        barsback: int = 1,
    ) -> list[dict[str, Any]]:
        """REST ``GET /v3/marketdata/barcharts/{symbol}`` (Daily / Weekly / Monthly — not stream)."""
        sym = symbol.strip()
        if not sym:
            raise BrokerValidationError("symbol is required")
        path_sym = _marketdata_path_symbol(sym)
        base = f"{self._market_data_url.rstrip('/')}/v3/marketdata/barcharts/{quote(path_sym, safe='')}"
        q = urlencode({"interval": str(interval), "unit": unit, "barsback": str(barsback)})
        url = f"{base}?{q}"
        data = await self._request_json("GET", url, tenant_id=tenant_id)
        if not isinstance(data, dict):
            return []
        bars = data.get("Bars") or data.get("bars")
        if not isinstance(bars, list):
            return []
        return [b for b in bars if isinstance(b, dict)]

    async def fetch_latest_daily_bar(self, symbol: str, tenant_id: str) -> Bar | None:
        """Most recent completed daily bar (``barsback=1``)."""
        rows = await self.fetch_barcharts_rest(
            symbol,
            tenant_id,
            interval="1",
            unit="Daily",
            barsback=1,
        )
        if not rows:
            return None
        sym = symbol.strip()
        return _bar_from_stream_obj(rows[-1], tenant_id, sym, "1D", symbol_for_bar=sym)

    def stream_quotes(self, symbols: list[str], tenant_id: str) -> AsyncIterator[Quote]:
        syms = [s.strip() for s in symbols if s.strip()]
        if not syms:
            async def _empty() -> AsyncIterator[Quote]:
                if False:  # pragma: no cover
                    yield Quote(tenant_id=tenant_id, symbol="")  # type: ignore[arg-type]

            return _empty()

        joined = ",".join(syms)

        async def _gen() -> AsyncIterator[Quote]:
            path = f"/v3/marketdata/stream/quotes/{quote(joined, safe=',')}"
            async for obj in self._iter_stream_objects(
                tenant_id, path, stream_base=self._market_stream_base_url
            ):
                if not isinstance(obj, dict):
                    continue
                if obj.get("StreamStatus") or obj.get("Error"):
                    continue
                q = _quote_from_stream_obj(obj, tenant_id)
                if q:
                    yield q

        return _gen()

    def stream_bars(self, symbol: str, interval: str, tenant_id: str) -> AsyncIterator[Bar]:
        sym = symbol.strip()
        if not sym:
            raise BrokerValidationError("symbol is required")
        try:
            unit, n = _barchart_unit_and_count(interval)
        except ValueError as e:
            raise BrokerValidationError(f"unsupported bar interval: {e}") from e
        q = f"interval={n}&unit={quote(unit, safe='')}"
        path_sym = _marketdata_path_symbol(sym)
        path = f"/v3/marketdata/stream/barcharts/{quote(path_sym, safe='')}?{q}"

        async def _gen() -> AsyncIterator[Bar]:
            # One long-lived HTTP chunked stream; reconnect only when the connection ends (caller may loop).
            self._last_barchart_stream_error = None
            meta_logged = 0
            bar_skip_logged = 0
            async for obj in self._iter_stream_objects(
                tenant_id, path, stream_base=self._market_stream_base_url
            ):
                if not isinstance(obj, dict):
                    continue
                # Keepalive: do not log or treat as bar (no OHLC).
                if "Heartbeat" in obj and "Close" not in obj and "close" not in obj:
                    continue
                if obj.get("StreamStatus") or obj.get("Error"):
                    blob = str(obj)
                    if "InvalidSymbol" in blob:
                        self._last_barchart_stream_error = "InvalidSymbol"
                    if meta_logged < 8:
                        print(f"[TS_STREAM] barchart {sym!r} (path={path_sym!r}) meta: {obj!r}")
                        meta_logged += 1
                    continue
                b = _bar_from_stream_obj(
                    obj, tenant_id, sym, interval, symbol_for_bar=sym
                )
                if b:
                    yield b
                elif "Close" not in obj and "Heartbeat" not in obj and bar_skip_logged < 6:
                    print(
                        f"[TS_STREAM] unexpected payload {sym!r} "
                        f"keys={list(obj.keys())[:5]!r}"
                    )
                    bar_skip_logged += 1

        return _gen()

    def stream_order_updates(self, account_id: str, tenant_id: str) -> AsyncIterator[OrderUpdate]:
        aid = account_id.strip()
        if not aid:
            raise BrokerValidationError("account_id is required")

        async def _gen() -> AsyncIterator[OrderUpdate]:
            path = f"/v3/brokerage/stream/accounts/{quote(aid, safe='')}/orders"
            async for obj in self._iter_stream_objects(
                tenant_id, path, stream_base=self._order_stream_base_url
            ):
                if not isinstance(obj, dict):
                    continue
                ss = obj.get("StreamStatus")
                if isinstance(ss, str) and ss.strip().lower().replace(" ", "") == "endofsnapshot":
                    yield OrderUpdate(
                        order_id="_stream_end_of_snapshot_",
                        tenant_id=tenant_id,
                        account_id=aid,
                        status=OrderStatus.SUBMITTED,
                        stream_marker="EndOfSnapshot",
                        raw=dict(obj),
                    )
                    continue
                if "Heartbeat" in obj and not (obj.get("OrderID") or obj.get("OrderId")):
                    continue
                if obj.get("StreamStatus") or obj.get("Error"):
                    continue
                ou = _order_update_from_stream(obj, tenant_id, aid)
                if ou:
                    yield ou

        return _gen()

    async def _iter_stream_objects(
        self,
        tenant_id: str,
        path: str,
        *,
        stream_base: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """HTTP chunked JSON stream (concatenated JSON values)."""
        base = stream_base.rstrip("/")
        url = f"{base}{path}"
        bearer = await self._bearer_token(tenant_id)
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.tradestation.streams.v3+json, application/vnd.tradestation.streams.v2+json, application/json",
        }
        # Long-lived streams: never time out reads; only bound connect.
        # This helps with idle periods and reduces disconnects from aggressive timeouts.
        timeout = httpx.Timeout(None, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code >= 400:
                        raise _map_http_exception(resp.status_code)
                    print(f"[TS_STREAM] HTTP stream opened status={resp.status_code} url={url}")
                    buf = ""
                    dec = json.JSONDecoder()
                    async for chunk in resp.aiter_text():
                        buf += chunk
                        buf, objs = _consume_json_objects(buf, dec)
                        for o in objs:
                            if isinstance(o, dict):
                                yield o
        except httpx.RequestError as e:
            raise BrokerNetworkError("stream connection failed") from e


def _http_base_from_ws_or_api(ws_base_url: str | None, api_base_url: str) -> str:
    """Normalize a stream base to an https:// origin for httpx streaming."""
    w = (ws_base_url or "").strip()
    if w.lower().startswith("wss://"):
        return "https://" + w[6:].rstrip("/")
    if w.lower().startswith("ws://"):
        return "http://" + w[5:].rstrip("/")
    if w:
        return w.rstrip("/")
    return api_base_url.rstrip("/")


def _consume_json_objects(buf: str, dec: json.JSONDecoder) -> tuple[str, list[Any]]:
    """Parse zero or more complete JSON values from the start of *buf*; return remainder + objects."""
    out: list[Any] = []
    rest = buf
    while rest.strip():
        idx = 0
        n = len(rest)
        while idx < n and rest[idx] in " \t\r\n":
            idx += 1
        if idx >= n:
            return "", out
        try:
            obj, end = dec.raw_decode(rest, idx)
            out.append(obj)
            rest = rest[end:]
        except json.JSONDecodeError:
            break
    return rest, out


def _parse_quote_payload(data: Any, symbol: str, tenant_id: str) -> Quote | None:
    if isinstance(data, dict) and "Quotes" in data:
        items = data.get("Quotes")
        if isinstance(items, list) and items:
            return _quote_from_stream_obj(items[0], tenant_id)
        return None
    if isinstance(data, list) and data:
        return _quote_from_stream_obj(data[0], tenant_id)
    if isinstance(data, dict):
        return _quote_from_stream_obj(data, tenant_id)
    return None


def _quote_from_stream_obj(obj: dict[str, Any], tenant_id: str) -> Quote | None:
    sym = _as_str(obj.get("Symbol")) or _as_str(obj.get("symbol"))
    if not sym:
        return None
    return Quote(
        tenant_id=tenant_id,
        symbol=sym,
        bid=_to_decimal(obj.get("Bid") or obj.get("BestBid")),
        ask=_to_decimal(obj.get("Ask") or obj.get("BestAsk")),
        last=_to_decimal(obj.get("Last") or obj.get("Close") or obj.get("LastPrice")),
        volume=_int_field(obj.get("Volume") or obj.get("LastVolume")),
        quote_time=_parse_ts(obj.get("TradeTime") or obj.get("TimeStamp") or obj.get("LastTradeTime")),
        raw=dict(obj),
    )


def _int_field(v: object) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v).replace(",", "").split(".")[0])
    except Exception:
        return None


def _parse_ts(v: object) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v) / 1000.0, tz=UTC)
        except Exception:
            return None
    s = str(v)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_account(data: Any, account_id: str, tenant_id: str) -> Account:
    if not isinstance(data, dict):
        raise BrokerValidationError("account response has unexpected shape")
    return Account(
        account_id=str(data.get("AccountID") or data.get("account_id") or account_id),
        tenant_id=tenant_id,
        name=_as_str(data.get("AccountName") or data.get("Name")),
        currency=str(data.get("Currency") or data.get("currency") or "USD"),
        buying_power=_to_decimal(data.get("BuyingPower") or data.get("DayTradingBuyingPower")),
        cash=_to_decimal(data.get("CashBalance") or data.get("Cash")),
        equity=_to_decimal(data.get("Equity") or data.get("NetLiquidation")),
        raw=dict(data),
    )


def _parse_order_submit_response(data: Any) -> tuple[str | None, OrderStatus]:
    if isinstance(data, dict):
        oid = data.get("OrderID") or data.get("OrderId")
        if oid is None and isinstance(data.get("Orders"), list) and data["Orders"]:
            o0 = data["Orders"][0]
            if isinstance(o0, dict):
                oid = o0.get("OrderID") or o0.get("OrderId")
        st = _map_ts_order_status(data.get("Status") or data.get("OrderStatus") or "")
        return (str(oid) if oid is not None else None, st)
    return (None, OrderStatus.NEW)


def _parse_positions(data: Any, account_id: str, tenant_id: str) -> list[Position]:
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        inner = data.get("Positions") or data.get("positions")
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
    out: list[Position] = []
    for r in rows:
        sym = _as_str(r.get("Symbol") or r.get("symbol"))
        if not sym:
            continue
        out.append(
            Position(
                account_id=account_id,
                tenant_id=tenant_id,
                symbol=sym,
                quantity=_to_decimal(r.get("Quantity") or r.get("NetQuantity")) or Decimal("0"),
                avg_cost=_to_decimal(r.get("AveragePrice") or r.get("AverageCost")),
                market_value=_to_decimal(r.get("MarketValue")),
                updated_at=_parse_ts(r.get("Updated") or r.get("TimeStamp")),
            )
        )
    return out


def _barchart_unit_and_count(interval: str) -> tuple[str, int]:
    """Map normalized interval (e.g. ``5m``, ``1h``) to TradeStation ``unit`` + ``interval`` count."""
    s = interval.strip().lower()
    if len(s) < 2:
        raise ValueError("interval too short")
    num_s, suf = s[:-1], s[-1]
    if not num_s.isdigit():
        raise ValueError("interval must be like 1m, 5m, 1h, 1d")
    n = int(num_s)
    if n <= 0:
        raise ValueError("interval must be positive")
    if suf == "s":
        return "Second", n
    if suf == "m":
        return "Minute", n
    if suf == "h":
        return "Hour", n
    if suf == "d":
        return "Day", n
    raise ValueError("suffix must be s, m, h, or d")


def _bar_from_stream_obj(
    obj: dict[str, Any],
    tenant_id: str,
    default_symbol: str,
    interval: str,
    *,
    symbol_for_bar: str | None = None,
) -> Bar | None:
    o = _to_decimal(obj.get("Open") or obj.get("open"))
    h = _to_decimal(obj.get("High") or obj.get("high"))
    l = _to_decimal(obj.get("Low") or obj.get("low"))
    c = _to_decimal(obj.get("Close") or obj.get("Last") or obj.get("close"))
    ts = _parse_ts(obj.get("TimeStamp") or obj.get("BarStartTime") or obj.get("DateTime") or obj.get("Time"))
    sym = (
        symbol_for_bar.strip()
        if symbol_for_bar
        else (_as_str(obj.get("Symbol") or obj.get("symbol")) or default_symbol)
    )
    vol_raw = obj.get("TotalVolume") or obj.get("Volume") or obj.get("UpDownVolume")
    vol: Decimal | int | None = _to_decimal(vol_raw) if vol_raw not in (None, "") else None
    if o is None or h is None or l is None or c is None or ts is None:
        return None
    return Bar(
        tenant_id=tenant_id,
        symbol=sym,
        interval=interval,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=vol,
        bar_start=ts,
        raw=dict(obj),
    )


def _order_update_from_stream(obj: dict[str, Any], tenant_id: str, account_id: str) -> OrderUpdate | None:
    oid = obj.get("OrderID") or obj.get("OrderId") or obj.get("Id")
    if oid is None and isinstance(obj.get("Order"), dict):
        o0 = obj["Order"]
        if isinstance(o0, dict):
            oid = o0.get("OrderID") or o0.get("OrderId") or o0.get("Id")
    if oid is None:
        return None
    oid = str(oid)
    event_parts = [obj.get("Event"), obj.get("MessageType"), obj.get("Type")]
    event_kind = " ".join(str(p) for p in event_parts if p) or None
    event_upper = (event_kind or "").upper()
    evt_single = _as_str(obj.get("Event")) or ""
    evt_u = evt_single.upper().replace(" ", "")

    sym = _as_str(
        obj.get("Symbol")
        or obj.get("symbol")
        or obj.get("Underlying")
        or obj.get("FullSymbol")
        or obj.get("LegSymbol")
    )
    ta = str(obj.get("TradeAction") or obj.get("Side") or obj.get("OrderSide") or "").upper()
    side: OrderSide | None = None
    if "BUY" in ta:
        side = OrderSide.BUY
    elif "SELL" in ta:
        side = OrderSide.SELL

    raw_st = obj.get("Status") or obj.get("OrderStatus") or obj.get("StatusDescription") or ""
    status = _map_ts_order_status(raw_st)
    if obj.get("RejectReason") or "REJECT" in event_upper or "REJECT" in evt_u:
        status = OrderStatus.REJECTED
    elif "PARTIAL" in evt_u or "PARTIALFILL" in evt_u:
        status = OrderStatus.PARTIALLY_FILLED
    elif evt_u in ("ORDERFILLED", "ORDERFILL") or (
        evt_u and "FILL" in evt_u and "PARTIAL" not in evt_u and "CONFIRM" not in evt_u
    ):
        if status not in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            status = OrderStatus.FILLED
    elif "CANCEL" in evt_u and status == OrderStatus.NEW:
        status = OrderStatus.CANCELLED

    msg = _as_str(obj.get("RejectReason") or obj.get("Message") or obj.get("Error"))

    filled_quantity = _to_decimal(
        obj.get("FilledQuantity")
        or obj.get("QuantityFilled")
        or obj.get("ExecQuantity")
        or obj.get("CumulativeFilled")
        or obj.get("CumulativeQuantity")
        or obj.get("Quantity")
    )
    avg_fill_price = _to_decimal(
        obj.get("AverageFillPrice")
        or obj.get("FilledPrice")
        or obj.get("AvgFillPrice")
        or obj.get("ExecutionPrice")
        or obj.get("AvgExecPrice")
        or obj.get("AvgPrice")
        or obj.get("Price")
        or obj.get("LastPrice")
    )

    is_snapshot: bool | None
    if "IsSnapshot" in obj:
        is_snapshot = bool(obj.get("IsSnapshot"))
    else:
        is_snapshot = None

    return OrderUpdate(
        order_id=oid,
        tenant_id=tenant_id,
        account_id=account_id,
        status=status,
        filled_quantity=filled_quantity,
        avg_fill_price=avg_fill_price,
        event_time=_parse_ts(
            obj.get("ClosedDateTime") or obj.get("Updated") or obj.get("TimeStamp") or obj.get("ExecutionTime")
        ),
        message=msg,
        symbol=sym,
        side=side,
        event_kind=event_kind,
        raw=dict(obj),
        is_snapshot=is_snapshot,
    )


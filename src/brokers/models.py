"""Platform-native broker models (no broker SDK types)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class InstrumentType(str, Enum):
    EQUITY = "equity"  # stocks, ETFs (e.g. SPY, AAPL)
    OPTIONS = "options"  # equity options
    FUTURES = "futures"  # ES, NQ, CL, GC etc.
    FUTURES_OPTIONS = "futures_options"


class BrokerCredentials(BaseModel):
    """Opaque credential bag for the initial auth handshake.

    Concrete adapters map these fields to broker-specific OAuth/API flows.
    No broker naming or vendor-specific enums belong here.
    """

    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(..., min_length=1, description="Tenant scope for token storage.")
    client_id: str | None = Field(default=None, description="OAuth client identifier.")
    client_secret: str | None = Field(default=None, description="OAuth client secret.")
    authorization_code: str | None = Field(
        default=None, description="One-time code from user authorization redirect."
    )
    redirect_uri: str | None = Field(default=None, description="Registered redirect URI.")
    extra: dict[str, Any] = Field(default_factory=dict, description="Adapter-specific safe metadata.")


class AuthToken(BaseModel):
    """Access session after authenticate or refresh."""

    model_config = ConfigDict(frozen=False)

    tenant_id: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scope: str | None = None


class Quote(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="Tenant scope for this quote snapshot.")
    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: int | None = None
    quote_time: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict, description="Non-portable fields, tenant-scoped.")


class Bar(BaseModel):
    """OHLCV bar in platform-native form (adapters map broker bar sizes to ``interval``)."""

    tenant_id: str = Field(..., min_length=1)
    symbol: str
    interval: str = Field(..., description="Normalized size, e.g. 1m, 5m, 1h, 1d.")
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | int | None = None
    bar_start: datetime
    bar_end: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Account(BaseModel):
    account_id: str
    tenant_id: str
    name: str | None = None
    currency: str = "USD"
    buying_power: Decimal | None = None
    cash: Decimal | None = None
    equity: Decimal | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str | None = None
    symbol: str
    instrument_type: InstrumentType = InstrumentType.EQUITY
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    strategy_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class OrderReceipt(BaseModel):
    order_id: str
    tenant_id: str
    status: OrderStatus
    submitted_at: datetime | None = None
    message: str | None = None


class CancelReceipt(BaseModel):
    order_id: str
    tenant_id: str
    cancelled: bool
    message: str | None = None


class Position(BaseModel):
    account_id: str
    tenant_id: str
    symbol: str
    quantity: Decimal
    avg_cost: Decimal | None = None
    market_value: Decimal | None = None
    updated_at: datetime | None = None


class OrderUpdate(BaseModel):
    order_id: str
    tenant_id: str
    account_id: str | None = Field(
        default=None,
        description="Broker account the order belongs to; adapters should set when known.",
    )
    status: OrderStatus
    filled_quantity: Decimal | None = None
    avg_fill_price: Decimal | None = None
    event_time: datetime | None = None
    message: str | None = None
    symbol: str | None = None
    side: OrderSide | None = None
    event_kind: str | None = Field(
        default=None,
        description="Vendor event name e.g. OrderFill, OrderReject (TradeStation stream).",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Original broker payload for persistence and debugging.",
    )
    is_snapshot: bool | None = Field(
        default=None,
        description="True when broker marks this payload as historical replay (e.g. IsSnapshot).",
    )
    stream_marker: str | None = Field(
        default=None,
        description="Non-order stream control events, e.g. EndOfSnapshot.",
    )

"""Pydantic models for API-facing tenant/domain DTOs (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TenantStatus(str, Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"


class TenantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str = Field(..., min_length=1)
    display_name: str = ""
    status: TenantStatus = TenantStatus.pending
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AccountDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    trading_mode: str
    broker_account_id: str
    name: str | None = None
    currency: str = "USD"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StrategyDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_kind: str
    owner_tenant_id: str | None = None
    name: str
    code_ref: str
    version: str | None = "1"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StrategyAllocationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    trading_mode: str
    strategy_id: str
    account_id: str | None = None
    allocation_amount: Decimal
    allocation_currency: str = "USD"
    risk_limits_ref: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    trading_mode: str
    account_id: str
    client_order_id: str | None = None
    broker_order_id: str | None = None
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    time_in_force: str
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    status: str
    submitted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PositionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    trading_mode: str
    account_id: str
    symbol: str
    quantity: Decimal
    avg_cost: Decimal | None = None
    market_value: Decimal | None = None
    updated_at: datetime | None = None


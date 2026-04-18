"""SQLAlchemy ORM models (Phase 1).

Source of truth: ``docs/database_schema.md``.

All tenant-owned tables include a non-null ``tenant_id`` (FK → ``tenants.tenant_id``) and
index it to make cross-tenant queries harder to accidentally write and easy to optimize.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


_JSON = JSON().with_variant(JSONB, "postgresql")


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class BrokerCredential(Base):
    __tablename__ = "broker_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "broker_name",
            "account_id_default",
            name="uq_broker_credentials_tenant_mode_broker_account",
        ),
        Index("ix_broker_credentials_lookup", "tenant_id", "trading_mode", "broker_name", "account_id_default"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    broker_name: Mapped[str] = mapped_column(String(64), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    ws_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    token_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    account_id_default: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "trading_mode", "broker_account_id", name="uq_accounts_tenant_mode_broker_account"
        ),
        Index("ix_accounts_tenant_mode", "tenant_id", "trading_mode"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    broker_account_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "account_id",
            "client_order_id",
            name="uq_orders_tenant_mode_account_client_order",
        ),
        Index("ix_orders_tenant_mode_created_at", "tenant_id", "trading_mode", "created_at"),
        Index("ix_orders_tenant_mode_account_created_at", "tenant_id", "trading_mode", "account_id", "created_at"),
        Index("ix_orders_tenant_mode_broker_order_id", "tenant_id", "trading_mode", "broker_order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="new")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "trading_mode", "account_id", "symbol", name="uq_positions_tenant_mode_account_symbol"
        ),
        Index("ix_positions_tenant_mode_account", "tenant_id", "trading_mode", "account_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        Index("ix_strategies_owner", "owner_kind", "owner_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    owner_tenant_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    code_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True, default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class StrategyAllocation(Base):
    __tablename__ = "strategy_allocations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "strategy_id",
            "account_id",
            name="uq_strategy_allocations_tenant_mode_strategy_account",
        ),
        Index("ix_strategy_allocations_tenant_mode", "tenant_id", "trading_mode"),
        Index("ix_strategy_allocations_tenant_mode_strategy", "tenant_id", "trading_mode", "strategy_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    allocation_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    allocation_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    risk_limits_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class MarketBar(Base):
    """Normalised OHLCV bars persisted per tenant (Timescale hypertable on Postgres in ops migrations)."""

    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "symbol",
            "bar_interval",
            "bar_start",
            name="uq_market_bars_tenant_mode_symbol_interval_start",
        ),
        Index(
            "ix_market_bars_tenant_symbol_interval_time",
            "tenant_id",
            "trading_mode",
            "symbol",
            "bar_interval",
            "bar_start",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bar_interval: Mapped[str] = mapped_column(String(16), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    bar_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class ExecutionSignal(Base):
    # PAPER TRADING MODE
    """Immutable signal decision record (tenant-scoped)."""

    __tablename__ = "execution_signals"
    __table_args__ = (
        Index("ix_exec_signals_tenant_mode_time", "tenant_id", "trading_mode", "generated_at"),
        Index("ix_exec_signals_tenant_mode_strategy", "tenant_id", "trading_mode", "strategy_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_strength: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=_now)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)


class ExecutionOrder(Base):
    # PAPER TRADING MODE
    """Order intent / placement record (tenant-scoped)."""

    __tablename__ = "execution_orders"
    __table_args__ = (
        Index("ix_exec_orders_tenant_mode_time", "tenant_id", "trading_mode", "created_at"),
        Index("ix_exec_orders_tenant_mode_strategy", "tenant_id", "trading_mode", "strategy_id"),
        Index("ix_exec_orders_tenant_mode_order_id", "tenant_id", "trading_mode", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=_now)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)


class DayTradeLog(Base):
    # PAPER TRADING MODE
    """Pattern day trade events for PDT surveillance (tenant-scoped)."""

    __tablename__ = "day_trade_log"
    __table_args__ = (Index("ix_day_trade_log_tenant_mode_time", "tenant_id", "trading_mode", "traded_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)


class ExecutionFill(Base):
    # PAPER TRADING MODE
    """Fill / order update record (tenant-scoped)."""

    __tablename__ = "execution_fills"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "trading_mode", "order_id", name="uq_exec_fills_tenant_mode_order"
        ),
        Index("ix_exec_fills_tenant_mode_time", "tenant_id", "trading_mode", "filled_at"),
        Index("ix_exec_fills_tenant_mode_order_id", "tenant_id", "trading_mode", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    fill_qty: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=_now)
    is_snapshot: Mapped[bool] = mapped_column(default=False, nullable=False)
    raw: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

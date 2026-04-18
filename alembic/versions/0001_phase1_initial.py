"""Phase 1 initial schema (multi-tenant).

Revision ID: 0001_phase1_initial
Revises:
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_phase1_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=128), primary_key=True),
        sa.Column("display_name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "broker_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("broker_name", sa.String(length=64), nullable=False),
        sa.Column("api_base_url", sa.String(length=512), nullable=False),
        sa.Column("ws_base_url", sa.String(length=512), nullable=False),
        sa.Column("token_url", sa.String(length=512), nullable=True),
        sa.Column("client_id", sa.String(length=256), nullable=True),
        sa.Column("client_secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(length=512), nullable=True),
        sa.Column("account_id_default", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "trading_mode", name="uq_broker_credentials_tenant_mode"),
    )
    op.create_index("ix_broker_credentials_tenant_mode", "broker_credentials", ["tenant_id", "trading_mode"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("broker_account_id", sa.String(length=128), nullable=False, index=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "trading_mode", "broker_account_id", name="uq_accounts_tenant_mode_broker_account"
        ),
    )
    op.create_index("ix_accounts_tenant_mode", "accounts", ["tenant_id", "trading_mode"])

    op.create_table(
        "strategies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_kind", sa.String(length=16), nullable=False, server_default="platform"),
        sa.Column(
            "owner_tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("code_ref", sa.String(length=512), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategies_owner", "strategies", ["owner_kind", "owner_tenant_id"])
    op.create_index("ix_strategies_owner_tenant_id", "strategies", ["owner_tenant_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), index=True),
        sa.Column("client_order_id", sa.String(length=128), nullable=True),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True, index=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("time_in_force", sa.String(length=16), nullable=False),
        sa.Column("limit_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new", index=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "account_id",
            "client_order_id",
            name="uq_orders_tenant_mode_account_client_order",
        ),
    )
    op.create_index("ix_orders_tenant_mode_created_at", "orders", ["tenant_id", "trading_mode", "created_at"])
    op.create_index(
        "ix_orders_tenant_mode_account_created_at", "orders", ["tenant_id", "trading_mode", "account_id", "created_at"]
    )
    op.create_index("ix_orders_tenant_mode_broker_order_id", "orders", ["tenant_id", "trading_mode", "broker_order_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), index=True),
        sa.Column("symbol", sa.String(length=32), nullable=False, index=True),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("avg_cost", sa.Numeric(24, 8), nullable=True),
        sa.Column("market_value", sa.Numeric(24, 8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "trading_mode", "account_id", "symbol", name="uq_positions_tenant_mode_account_symbol"
        ),
    )
    op.create_index("ix_positions_tenant_mode_account", "positions", ["tenant_id", "trading_mode", "account_id"])

    op.create_table(
        "strategy_allocations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(length=36), sa.ForeignKey("strategies.id", ondelete="CASCADE"), index=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("allocation_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("allocation_currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("risk_limits_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "strategy_id",
            "account_id",
            name="uq_strategy_allocations_tenant_mode_strategy_account",
        ),
    )
    op.create_index("ix_strategy_allocations_tenant_mode", "strategy_allocations", ["tenant_id", "trading_mode"])
    op.create_index(
        "ix_strategy_allocations_tenant_mode_strategy",
        "strategy_allocations",
        ["tenant_id", "trading_mode", "strategy_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_allocations_tenant_mode_strategy", table_name="strategy_allocations")
    op.drop_index("ix_strategy_allocations_tenant_mode", table_name="strategy_allocations")
    op.drop_table("strategy_allocations")

    op.drop_index("ix_positions_tenant_mode_account", table_name="positions")
    op.drop_table("positions")

    op.drop_index("ix_orders_tenant_mode_broker_order_id", table_name="orders")
    op.drop_index("ix_orders_tenant_mode_account_created_at", table_name="orders")
    op.drop_index("ix_orders_tenant_mode_created_at", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_strategies_owner_tenant_id", table_name="strategies")
    op.drop_index("ix_strategies_owner", table_name="strategies")
    op.drop_table("strategies")

    op.drop_index("ix_accounts_tenant_mode", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_broker_credentials_tenant_mode", table_name="broker_credentials")
    op.drop_table("broker_credentials")

    op.drop_table("tenants")


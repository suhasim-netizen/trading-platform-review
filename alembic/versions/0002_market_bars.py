"""Add market_bars for normalised OHLCV storage (Timescale-ready).

Revision ID: 0002_market_bars
Revises: 0001_phase1_initial
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_market_bars"
down_revision = "0001_phase1_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_bars",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("symbol", sa.String(length=32), nullable=False, index=True),
        sa.Column("bar_interval", sa.String(length=16), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("bar_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "trading_mode",
            "symbol",
            "bar_interval",
            "bar_start",
            name="uq_market_bars_tenant_mode_symbol_interval_start",
        ),
    )
    op.create_index(
        "ix_market_bars_tenant_symbol_interval_time",
        "market_bars",
        ["tenant_id", "trading_mode", "symbol", "bar_interval", "bar_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_bars_tenant_symbol_interval_time", table_name="market_bars")
    op.drop_table("market_bars")

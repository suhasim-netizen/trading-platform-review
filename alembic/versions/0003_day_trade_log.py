"""Add day_trade_log table for PDT / intraday tracking.

Revision ID: 0003_day_trade_log
Revises: 0002_market_bars
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_day_trade_log"
down_revision = "0002_market_bars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_trade_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=128),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False, index=True),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, index=True),
    )
    op.create_index(
        "ix_day_trade_log_tenant_mode_time",
        "day_trade_log",
        ["tenant_id", "trading_mode", "traded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_day_trade_log_tenant_mode_time", table_name="day_trade_log")
    op.drop_table("day_trade_log")

"""Add is_snapshot to execution_fills for order-stream replay deduplication.

Revision ID: 0004_execution_fills_is_snapshot
Revises: 0003_day_trade_log
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_execution_fills_is_snapshot"
down_revision = "0003_day_trade_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_fills",
        sa.Column("is_snapshot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("execution_fills", "is_snapshot")

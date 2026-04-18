"""Positions store broker account id; unique execution_fills per order.

Revision ID: 0005_positions_broker_account_fills_unique
Revises: 0004_execution_fills_is_snapshot
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "0005_positions_broker_account_fills_unique"
down_revision = "0004_execution_fills_is_snapshot"
branch_labels = None
depends_on = None


def _dedupe_execution_fills(conn) -> None:
    # Keep one row per (tenant_id, trading_mode, order_id); prefer smallest id.
    conn.execute(
        text(
            """
            DELETE FROM execution_fills
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM execution_fills
                GROUP BY tenant_id, trading_mode, order_id
            )
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    _dedupe_execution_fills(conn)
    op.create_unique_constraint(
        "uq_exec_fills_tenant_mode_order",
        "execution_fills",
        ["tenant_id", "trading_mode", "order_id"],
    )

    # Map positions.account_id from accounts.id UUID to accounts.broker_account_id
    if dialect == "postgresql":
        op.drop_constraint("positions_account_id_fkey", "positions", type_="foreignkey")
        conn.execute(
            text(
                """
                UPDATE positions AS p
                SET account_id = a.broker_account_id
                FROM accounts AS a
                WHERE p.account_id = a.id
                """
            )
        )
        op.alter_column(
            "positions",
            "account_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
    else:
        # SQLite: recreate table to drop FK and widen account_id
        with op.batch_alter_table("positions", recreate="always") as batch_op:
            batch_op.alter_column(
                "account_id",
                existing_type=sa.String(length=36),
                type_=sa.String(length=64),
                existing_nullable=False,
            )

        # After recreate, batch_alter may not run UPDATE; re-fetch and fix broker ids
        conn.execute(
            text(
                """
                UPDATE positions
                SET account_id = (
                    SELECT broker_account_id FROM accounts
                    WHERE accounts.id = positions.account_id
                )
                WHERE EXISTS (
                    SELECT 1 FROM accounts WHERE accounts.id = positions.account_id
                )
                """
            )
        )
        # Rows still holding UUID (no matching account) — leave as-is for manual cleanup


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    op.drop_constraint("uq_exec_fills_tenant_mode_order", "execution_fills", type_="unique")

    if dialect == "postgresql":
        op.alter_column(
            "positions",
            "account_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=36),
            existing_nullable=False,
        )
        conn.execute(
            text(
                """
                UPDATE positions AS p
                SET account_id = a.id
                FROM accounts AS a
                WHERE p.account_id = a.broker_account_id
                  AND p.tenant_id = a.tenant_id
                  AND p.trading_mode = a.trading_mode
                """
            )
        )
        op.create_foreign_key(
            "positions_account_id_fkey",
            "positions",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
    else:
        with op.batch_alter_table("positions", recreate="always") as batch_op:
            batch_op.alter_column(
                "account_id",
                existing_type=sa.String(length=64),
                type_=sa.String(length=36),
                existing_nullable=False,
            )
        op.create_foreign_key(
            "positions_account_id_fkey",
            "positions",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

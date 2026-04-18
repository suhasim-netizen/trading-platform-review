"""Restore positions.account_id as FK to accounts.id (UUID) after 0005 broker-string experiment.

Revision ID: 0006_positions_account_fk_uuid
Revises: 0005_positions_broker_account_fills_unique
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "0006_positions_account_fk_uuid"
down_revision = "0005_positions_broker_account_fills_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    conn.execute(
        text(
            """
            UPDATE positions AS p
            SET account_id = (
                SELECT a.id FROM accounts AS a
                WHERE a.tenant_id = p.tenant_id
                  AND a.trading_mode = p.trading_mode
                  AND a.broker_account_id = p.account_id
            )
            WHERE EXISTS (
                SELECT 1 FROM accounts AS a
                WHERE a.tenant_id = p.tenant_id
                  AND a.trading_mode = p.trading_mode
                  AND a.broker_account_id = p.account_id
            )
            """
        )
    )

    if dialect == "postgresql":
        conn.execute(text("ALTER TABLE positions DROP CONSTRAINT IF EXISTS positions_account_id_fkey"))
        op.alter_column(
            "positions",
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


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

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
        op.drop_constraint("positions_account_id_fkey", "positions", type_="foreignkey")
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
        with op.batch_alter_table("positions", recreate="always") as batch_op:
            batch_op.alter_column(
                "account_id",
                existing_type=sa.String(length=36),
                type_=sa.String(length=64),
                existing_nullable=False,
            )

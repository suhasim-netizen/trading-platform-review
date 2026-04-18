# PAPER TRADING MODE

"""Execution event persistence (tenant-scoped DB writes only).

ADR 0002: persist immutable records for signals, orders, and fills with mandatory tenant_id scoping.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from brokers.models import Order, OrderReceipt, OrderUpdate
from db.models import ExecutionFill, ExecutionOrder, ExecutionSignal
from db.session import get_session_factory

from .models import Signal


class ExecutionLogger:
    def __init__(self, *, tenant_id: str, trading_mode: str) -> None:
        if not tenant_id or not trading_mode:
            raise ValueError("tenant_id and trading_mode are required")
        self._tenant_id = tenant_id
        self._trading_mode = trading_mode

    def _guard(self, tenant_id: str, trading_mode: str) -> None:
        if tenant_id != self._tenant_id or trading_mode != self._trading_mode:
            raise ValueError("tenant_id/trading_mode mismatch")

    def log_signal(self, signal: Signal) -> None:
        self._guard(signal.tenant_id, signal.trading_mode)
        factory = get_session_factory()
        with factory() as session:
            with session.begin():
                session.add(
                    ExecutionSignal(
                        tenant_id=signal.tenant_id,
                        trading_mode=signal.trading_mode,
                        strategy_id=signal.strategy_id,
                        symbol=signal.symbol,
                        signal_type=signal.signal_type.value,
                        signal_strength=signal.signal_strength,
                        generated_at=signal.generated_at,
                        raw=signal.params,
                    )
                )

    def log_order(self, *, strategy_id: str, order: Order, receipt: OrderReceipt) -> None:
        self._guard(receipt.tenant_id, self._trading_mode)
        factory = get_session_factory()
        with factory() as session:
            with session.begin():
                session.add(
                    ExecutionOrder(
                        tenant_id=receipt.tenant_id,
                        trading_mode=self._trading_mode,
                        strategy_id=strategy_id,
                        order_id=receipt.order_id,
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=Decimal(str(order.quantity)),
                        order_type=order.order_type.value,
                        status=receipt.status.value,
                        created_at=receipt.submitted_at or datetime.now(UTC),
                        raw={"message": receipt.message} if receipt.message else None,
                    )
                )

    def log_fill(
        self,
        *,
        update: OrderUpdate,
        raw: dict[str, Any] | None = None,
        is_snapshot: bool = False,
    ) -> bool:
        self._guard(update.tenant_id, self._trading_mode)
        factory = get_session_factory()
        with factory() as session:
            with session.begin():
                existing = session.execute(
                    select(ExecutionFill.id).where(
                        ExecutionFill.tenant_id == update.tenant_id,
                        ExecutionFill.trading_mode == self._trading_mode,
                        ExecutionFill.order_id == update.order_id,
                    ).limit(1)
                ).scalar_one_or_none()
                if existing is not None:
                    return False
                session.add(
                    ExecutionFill(
                        tenant_id=update.tenant_id,
                        trading_mode=self._trading_mode,
                        order_id=update.order_id,
                        fill_price=Decimal(str(update.avg_fill_price)) if update.avg_fill_price is not None else None,
                        fill_qty=Decimal(str(update.filled_quantity)) if update.filled_quantity is not None else None,
                        filled_at=update.event_time or datetime.now(UTC),
                        is_snapshot=is_snapshot,
                        raw=raw,
                    )
                )
                return True




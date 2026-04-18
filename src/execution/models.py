# PAPER TRADING MODE

"""Execution framework internal models (tenant-scoped, broker-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    ENTER = "enter"
    EXIT = "exit"
    FLATTEN = "flatten"
    REBALANCE = "rebalance"
    TARGET_WEIGHTS = "target_weights"


@dataclass(frozen=True, slots=True)
class Signal:
    tenant_id: str
    trading_mode: str
    strategy_id: str
    symbol: str
    signal_type: SignalType
    signal_strength: Decimal | None = None
    account_id: str | None = None
    generated_at: datetime = datetime.now(UTC)
    params: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str | None = None


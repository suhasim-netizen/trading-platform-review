"""Request-scoped tenant and trading mode (paper vs live) — never infer from payload alone."""

from __future__ import annotations

import contextvars
from enum import Enum

_tenant_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
_trading_mode_var: contextvars.ContextVar["TradingMode | None"] = contextvars.ContextVar(
    "trading_mode", default=None
)


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


def set_tenant_context(*, tenant_id: str, trading_mode: TradingMode) -> None:
    _tenant_id_var.set(tenant_id)
    _trading_mode_var.set(trading_mode)


def get_tenant_id() -> str:
    tid = _tenant_id_var.get()
    if not tid:
        raise RuntimeError("tenant_id is not set in context")
    return tid


def get_trading_mode() -> TradingMode:
    mode = _trading_mode_var.get()
    if mode is None:
        raise RuntimeError("trading_mode is not set in context")
    return mode


def clear_tenant_context() -> None:
    _tenant_id_var.set(None)
    _trading_mode_var.set(None)

# PAPER TRADING MODE

"""Strategy 001 — placeholder until alpha is implemented (see docs/strategies/strategy_001_v0.1.0.md)."""

from __future__ import annotations

from typing import Any


class EquityMomentumSP500Placeholder:
    name = "strategy_001"

    def on_bar(self, symbol: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        return None


HANDLER_CLASS = EquityMomentumSP500Placeholder

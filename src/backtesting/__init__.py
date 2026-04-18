"""Backtesting package — simulation and performance metrics (Director / internal)."""

from __future__ import annotations

from .engine import BacktestEngine
from .models import BacktestResult

__all__ = ["BacktestEngine", "BacktestResult"]

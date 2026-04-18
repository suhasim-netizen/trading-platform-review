"""Backtest result models — scoped by strategy id, version, and tenant."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    version: str
    tenant_id: str
    start_date: str
    end_date: str
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    total_return: float
    win_rate: float
    profit_factor: float
    num_trades: int
    in_sample_sharpe: float
    out_of_sample_sharpe: float

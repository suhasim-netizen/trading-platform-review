"""Momentum strategy backtest engine.

This module supports running Strategy 001 using a local CSV price source for reliability.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .models import BacktestResult

logger = logging.getLogger(__name__)

# Set by the last run (used by report generator).
LAST_RUN_DATA_MODE: str = "unknown"

DEFAULT_STRATEGY_001_SPEC: dict[str, Any] = {
    "strategy_id": "strategy_001",
    "version": "0.1.0",
    # In the current local-data setup we run on SPY only.
    "symbol": "SPY",
    "momentum_skip_short": 21,
    "momentum_lookback_long": 273,
    "slippage_bps_per_side": 10.0,
    "commission_per_trade_usd": 0.0,
}

def _stooq_daily(sym: str, start: str, end: str) -> pd.DataFrame:
    """Fallback daily OHLCV from Stooq CSV when Yahoo JSON fails (rate limits / blocks)."""
    s = sym.strip()
    if s.startswith("^"):
        stooq_s = s.lower()
    else:
        stooq_s = s.lower() + ".us"
    q = urllib.parse.quote(stooq_s, safe="")
    url = f"https://stooq.com/q/d/l/?s={q}&i=d"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            df = pd.read_csv(resp)
    except Exception as e:  # noqa: BLE001
        logger.debug("stooq %s: %s", sym, e)
        return pd.DataFrame()
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], utc=False)
    df = df.set_index("Date").sort_index()
    ts0, ts1 = pd.Timestamp(start), pd.Timestamp(end)
    df = df.loc[(df.index >= ts0) & (df.index < ts1)]
    return df


def _last_trading_day_per_month(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(np.arange(len(idx)), index=idx)
    return pd.DatetimeIndex(s.groupby(idx.to_period("M")).apply(lambda x: x.index.max()))


def _rebalance_holdings(
    prev: set[str],
    ranked: list[str],
    *,
    top_n: int,
    exit_rank: int,
) -> set[str]:
    rank_map = {sym: i + 1 for i, sym in enumerate(ranked)}
    eligible = set(ranked)
    survivors = [s for s in prev if s in eligible and rank_map[s] < exit_rank]
    survivors.sort(key=lambda s: rank_map[s])
    if len(survivors) > top_n:
        survivors = survivors[:top_n]
    new_h: set[str] = set(survivors)
    for sym in ranked[:top_n]:
        if len(new_h) >= top_n:
            break
        if sym not in new_h:
            new_h.add(sym)
    return new_h


def _weights_vector(holdings: set[str]) -> dict[str, float]:
    if not holdings:
        return {}
    w = 1.0 / len(holdings)
    return {s: w for s in holdings}


def _turnover_cost_fraction(w_old: np.ndarray, w_new: np.ndarray, slippage_bps_per_side: float) -> float:
    dw = float(np.abs(w_new - w_old).sum())
    half_turn = 0.5 * dw
    return float(half_turn * 2.0 * slippage_bps_per_side / 10_000.0)


def _metrics_from_returns(ret: pd.Series) -> dict[str, float]:
    """Risk/return stats from daily simple returns (numpy/pandas; no vectorbt)."""
    ret = ret.dropna().astype(float)
    if ret.empty:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
        }
    arr = ret.values
    ann = 252.0
    mean_d = float(np.mean(arr))
    std_d = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    sharpe = (np.sqrt(ann) * mean_d / std_d) if std_d > 1e-12 else 0.0

    downside_dev = float(np.sqrt(np.mean(np.minimum(0.0, arr) ** 2)))
    sortino = (np.sqrt(ann) * mean_d / downside_dev) if downside_dev > 1e-12 else 0.0

    cum = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = float(np.min(dd)) if len(dd) else 0.0

    total_ret = float(np.prod(1.0 + arr) - 1.0)
    n = max(len(arr), 1)
    years = n / ann
    ann_ret = (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 1e-9 else total_ret
    calmar = float(ann_ret / abs(max_dd)) if max_dd < -1e-12 else 0.0

    pos_sum = float(arr[arr > 0].sum())
    neg_sum = float(arr[arr < 0].sum())
    if neg_sum < 0:
        pf = pos_sum / abs(neg_sum)
    else:
        pf = float("inf") if pos_sum > 0 else 0.0

    return {
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sortino),
        "calmar_ratio": float(calmar),
        "max_drawdown": float(max_dd),
        "total_return": float(total_ret),
        "win_rate": float((arr > 0).mean()),
        "profit_factor": float(pf) if np.isfinite(pf) else 0.0,
    }


@dataclass
class SimulationOutcome:
    daily_returns: pd.Series
    num_trades: int


def simulate_strategy_001_from_close(
    close: pd.Series,
    *,
    start_date: str,
    end_date: str,
    momentum_skip_short: int,
    momentum_lookback_long: int,
    slippage_bps_per_side: float,
) -> SimulationOutcome:
    """Monthly 12–1 momentum on a single instrument (SPY)."""
    idx = close.index
    close = close.astype(float).sort_index()
    close = close.loc[(close.index >= pd.Timestamp(start_date)) & (close.index < pd.Timestamp(end_date))]
    if close.empty:
        raise RuntimeError("No prices in requested date range.")

    month_ends = _last_trading_day_per_month(close.index)

    S = int(momentum_skip_short)
    L = int(momentum_lookback_long)
    slip = float(slippage_bps_per_side)

    w = np.zeros(len(close.index), dtype=float)
    cost_hit = np.zeros(len(close.index), dtype=float)
    trades = 0

    prev_w = 0.0
    for T in month_ends:
        ti = int(close.index.get_indexer([T])[0])
        if ti < 0:
            continue
        eff_i = ti + 1
        if eff_i >= len(close.index):
            continue
        if ti < L:
            new_w = 0.0
        else:
            p_short = float(close.iloc[ti - S])
            p_long = float(close.iloc[ti - L])
            new_w = 1.0 if (np.isfinite(p_short) and np.isfinite(p_long) and p_long > 0) else 0.0

        if new_w != prev_w:
            trades += 1
        cost_hit[eff_i] += abs(new_w - prev_w) * slip / 10_000.0
        w[eff_i:] = new_w
        prev_w = new_w

    rets = close.pct_change().fillna(0.0).values
    port = w[:-1] * rets[1:] - cost_hit[1:]
    daily = pd.Series(np.concatenate([[0.0], port]), index=close.index, name="port_ret")
    return SimulationOutcome(daily_returns=daily, num_trades=trades)


def compute_window_metrics(daily_returns: pd.Series, start: str, end: str) -> dict[str, float]:
    sl = daily_returns.loc[(daily_returns.index >= pd.Timestamp(start)) & (daily_returns.index < pd.Timestamp(end))]
    return _metrics_from_returns(sl)


class BacktestEngine:
    def _fetch_price_data(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        csv_path = Path("data") / f"{symbol.lower()}_2023_2026.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Local data file not found: {csv_path}. "
                f"Download from: "
                f"https://stooq.com/q/d/l/?s=spy.us&d1=20230101&d2=20260101&i=d"
            )
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[start:end]
        return df

    def run(self, *args: Any, **kwargs: Any) -> BacktestResult:
        """Run Strategy 001 simulation.

        Call either ``run(strategy_spec, start_date, end_date, tenant_id)`` (legacy) or
        ``run(start_date=..., end_date=..., tenant_id=..., strategy_id=..., version=..., **spec_overrides)``.
        """
        if len(args) >= 4 and isinstance(args[0], dict):
            strategy_spec = args[0]
            start_date, end_date, tenant_id = str(args[1]), str(args[2]), str(args[3])
            spec = {**DEFAULT_STRATEGY_001_SPEC, **strategy_spec}
        elif kwargs:
            start_date = str(kwargs.pop("start_date"))
            end_date = str(kwargs.pop("end_date"))
            tenant_id = str(kwargs.pop("tenant_id"))
            spec = {**DEFAULT_STRATEGY_001_SPEC, **kwargs}
        else:
            raise TypeError(
                "Expected run({strategy_spec}, start_date, end_date, tenant_id) or "
                "run(start_date=..., end_date=..., tenant_id=..., ...)"
            )

        symbol = str(spec.get("symbol") or "SPY")
        px = self._fetch_price_data(symbol, start=start_date, end=end_date)
        if "close" not in px.columns:
            raise RuntimeError("CSV missing Close column")

        out = simulate_strategy_001_from_close(
            px["close"],
            start_date=start_date,
            end_date=end_date,
            momentum_skip_short=int(spec["momentum_skip_short"]),
            momentum_lookback_long=int(spec["momentum_lookback_long"]),
            slippage_bps_per_side=float(spec["slippage_bps_per_side"]),
        )
        global LAST_RUN_DATA_MODE  # noqa: PLW0603
        LAST_RUN_DATA_MODE = "REAL (CSV — SPY daily from Stooq)"

        daily_report = out.daily_returns
        return _backtest_result_from_series(daily_report, spec, start_date, end_date, tenant_id, out.num_trades)


def _backtest_result_from_series(
    daily_report: pd.Series,
    spec: dict[str, Any],
    start_date: str,
    end_date: str,
    tenant_id: str,
    num_trades: int,
) -> BacktestResult:
    full_metrics = _metrics_from_returns(daily_report)
    # Default split: 80% IS / 20% OOS unless explicitly provided.
    split_raw = spec.get("in_sample_end") or spec.get("oos_start")
    if split_raw:
        split = pd.Timestamp(str(split_raw))
    else:
        s0 = pd.Timestamp(start_date)
        s1 = pd.Timestamp(end_date)
        split = s0 + (s1 - s0) * 0.8
    is_sh = float(
        _metrics_from_returns(
            daily_report.loc[
                (daily_report.index >= pd.Timestamp(start_date)) & (daily_report.index < split)
            ]
        )["sharpe_ratio"]
    )
    oos_sh = float(
        _metrics_from_returns(
            daily_report.loc[
                (daily_report.index >= split) & (daily_report.index < pd.Timestamp(end_date))
            ]
        )["sharpe_ratio"]
    )
    return BacktestResult(
        strategy_id=str(spec["strategy_id"]),
        version=str(spec["version"]),
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        sharpe_ratio=full_metrics["sharpe_ratio"],
        sortino_ratio=full_metrics["sortino_ratio"],
        calmar_ratio=full_metrics["calmar_ratio"],
        max_drawdown=full_metrics["max_drawdown"],
        total_return=full_metrics["total_return"],
        win_rate=full_metrics["win_rate"],
        profit_factor=full_metrics["profit_factor"],
        num_trades=num_trades,
        in_sample_sharpe=is_sh,
        out_of_sample_sharpe=oos_sh,
    )


def run_strategy001_daily_and_result(
    start_date: str = "2021-01-01",
    end_date: str = "2024-01-01",
    tenant_id: str = "director",
    strategy_spec: dict[str, Any] | None = None,
) -> tuple[pd.Series, BacktestResult]:
    """Run simulation once; return sliced daily returns + ``BacktestResult`` for reporting."""
    spec = {**DEFAULT_STRATEGY_001_SPEC, **(strategy_spec or {})}
    out = simulate_strategy_001(spec, start_date, end_date)
    daily_report = out.daily_returns.loc[
        (out.daily_returns.index >= pd.Timestamp(start_date)) & (out.daily_returns.index < pd.Timestamp(end_date))
    ]
    result = _backtest_result_from_series(daily_report, spec, start_date, end_date, tenant_id, out.num_trades)
    return daily_report, result

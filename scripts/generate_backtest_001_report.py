"""Generate docs/backtests/backtest_001_v0.1.0_results.md from one Strategy 001 run."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yfinance as yf

import src.backtesting.engine as _engine  # noqa: E402

from src.backtesting.engine import (  # noqa: E402
    _yfinance_session,
    compute_window_metrics,
    run_strategy001_daily_and_result,
)


def _pct(x: float) -> str:
    if x != x:
        return "—"
    return f"{100.0 * x:.2f}"


def _num(x: float, nd: int = 3) -> str:
    if x != x:
        return "—"
    return f"{x:.{nd}f}"


def _bench_return(start: str, end: str) -> float:
    sess = _yfinance_session()
    t = yf.Ticker("^GSPC", session=sess)
    h = t.history(start=start, end=end, auto_adjust=True, repair=True)
    if h.empty or "Close" not in h.columns:
        return float("nan")
    c = h["Close"].astype(float)
    return float(c.iloc[-1] / c.iloc[0] - 1.0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2024-01-01")
    p.add_argument("--tenant", default="director")
    p.add_argument("--report-date", default="2026-04-15")
    args = p.parse_args()

    import vectorbt as vbt

    daily, result = run_strategy001_daily_and_result(
        start_date=args.start,
        end_date=args.end,
        tenant_id=args.tenant,
        strategy_spec={"strategy_id": "strategy_001", "version": "0.1.0"},
    )
    last_mode = _engine.LAST_RUN_DATA_MODE

    is_m = compute_window_metrics(daily, args.start, "2023-01-01")
    oos_m = compute_window_metrics(daily, "2023-01-01", args.end)

    wf = [
        ("1", "2021 H1", "2021-01-01", "2021-07-01"),
        ("2", "2021 H2–2022 H1", "2021-07-01", "2022-07-01"),
        ("3", "2022 H2–2023 H1", "2022-07-01", "2023-07-01"),
        ("4", "2023 H2–2024 H1", "2023-07-01", args.end),
    ]
    wf_rows = []
    for wid, label, ws, we in wf:
        m = compute_window_metrics(daily, ws, we)
        wf_rows.append(
            f"| {wid} | {label} ({ws} to {we}) | {_num(m['sharpe_ratio'])} | {_pct(m['max_drawdown'])} |"
        )

    y2021_s, y2021_e = "2021-01-01", "2022-01-01"
    y2022_s, y2022_e = "2022-01-01", "2023-01-01"
    y2023_s, y2023_e = "2023-01-01", args.end
    s2021 = compute_window_metrics(daily, y2021_s, y2021_e)["total_return"]
    s2022 = compute_window_metrics(daily, y2022_s, y2022_e)["total_return"]
    s2023 = compute_window_metrics(daily, y2023_s, y2023_e)["total_return"]
    b2021 = _bench_return(y2021_s, y2021_e)
    b2022 = _bench_return(y2022_s, y2022_e)
    b2023 = _bench_return(y2023_s, y2023_e)

    sharpe_ok = result.sharpe_ratio >= 0.8
    dd_ok = abs(result.max_drawdown) <= 0.25
    oos_ok = result.out_of_sample_sharpe >= 0.6
    verdict = "PASS" if (sharpe_ok and dd_ok and oos_ok) else "FAIL"

    out_dir = ROOT / "docs" / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "backtest_001_v0.1.0_results.md"

    data_note = (
        "Synthetic GBM price panel (seeded); Yahoo was unavailable/blocked — use TradeStation Phase 3 for production."
        if last_mode == "synthetic"
        else "Yahoo Finance daily OHLCV (split-adjusted closes)."
    )

    md = f"""# Backtest Report — Strategy 001 v0.1.0
Date: {args.report_date}
Tenant: {args.tenant}
Data source: yfinance {yf.__version__}
Engine: vectorbt {vbt.__version__}

**Data note:** {data_note} Simulation and risk statistics use **pandas/numpy** (see ``src/backtesting/engine.py``); vectorbt is available in the environment but not required for this run.

## Performance Summary
| Metric | In-Sample | Out-of-Sample |
|--------|-----------|---------------|
| Sharpe ratio | {_num(is_m["sharpe_ratio"])} | {_num(oos_m["sharpe_ratio"])} |
| Sortino ratio | {_num(is_m["sortino_ratio"])} | {_num(oos_m["sortino_ratio"])} |
| Calmar ratio | {_num(is_m["calmar_ratio"])} | {_num(oos_m["calmar_ratio"])} |
| Max drawdown % | {_pct(is_m["max_drawdown"])} | {_pct(oos_m["max_drawdown"])} |
| Total return % | {_pct(is_m["total_return"])} | {_pct(oos_m["total_return"])} |
| Win rate % | {_pct(is_m["win_rate"])} | {_pct(oos_m["win_rate"])} |
| Number of trades | {result.num_trades} | {result.num_trades} |

*In-sample: {args.start}–2023-01-01; out-of-sample: 2023-01-01–{args.end}. Trade count = position-change events (full window, not split by IS/OOS).*

## Walk-forward Results
| Window | Period | Sharpe | Max DD % |
|--------|--------|--------|----------|
{chr(10).join(wf_rows)}

## Regime Analysis
| Period | Market | Strategy Return | Benchmark |
|--------|--------|-----------------|----------|
| 2021 | Bull | {_pct(s2021)} | {_pct(b2021)} (^GSPC) |
| 2022 | Bear | {_pct(s2022)} | {_pct(b2022)} (^GSPC) |
| 2023 | Recovery | {_pct(s2023)} | {_pct(b2023)} (^GSPC) |

## Transaction Cost Assumptions
- Commission: $0 per trade (paper trading)
- Slippage: 0.1% per trade assumed (implemented as **10 bps per side** on turnover at each monthly rebalance)
- Rebalance frequency: Monthly

## Verdict
**{verdict}**

Sharpe ≥ 0.8: {"✓" if sharpe_ok else "✗"} (full-window Sharpe {_num(result.sharpe_ratio)})

Max drawdown ≤ 25%: {"✓" if dd_ok else "✗"} (max DD {_pct(result.max_drawdown)})

Out-of-sample Sharpe ≥ 0.6: {"✓" if oos_ok else "✗"} (OOS Sharpe {_num(result.out_of_sample_sharpe)})
"""
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

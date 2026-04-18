"""Generate docs/backtests/backtest_001_v0.1.0_results.md — requires network for yfinance."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtesting.engine import (  # noqa: E402
    compute_window_metrics,
    run_strategy001_daily_and_result,
)


def _fmt_float(x: float, nd: int = 3) -> str:
    if x != x:  # noqa: PLR0124
        return "nan"
    return f"{x:.{nd}f}"


def _fmt_pct(x: float) -> str:
    return f"{100.0 * x:.2f}%"


def main() -> None:
    start_date = "2021-01-01"
    end_date = "2024-01-01"
    tenant_id = "director"

    daily, result = run_strategy001_daily_and_result(
        start_date=start_date,
        end_date=end_date,
        tenant_id=tenant_id,
    )

    is_m = compute_window_metrics(daily, "2021-01-01", "2023-01-01")
    oos_m = compute_window_metrics(daily, "2023-01-01", end_date)

    wf_windows = [
        ("2021 (bull regime)", "2021-01-01", "2022-01-01"),
        ("2022 (bear regime)", "2022-01-01", "2023-01-01"),
        ("2023 H1 (recovery)", "2023-01-01", "2023-07-01"),
        ("2023 H2 – 2024", "2023-07-01", end_date),
    ]
    wf_lines = []
    for label, ws, we in wf_windows:
        m = compute_window_metrics(daily, ws, we)
        wf_lines.append(
            f"- **{label}** ({ws} to {we}): "
            f"Sharpe {_fmt_float(m['sharpe_ratio'])}, "
            f"total return {_fmt_pct(m['total_return'])}, "
            f"max DD {_fmt_pct(m['max_drawdown'])}"
        )

    m_2021 = compute_window_metrics(daily, "2021-01-01", "2022-01-01")
    m_2022 = compute_window_metrics(daily, "2022-01-01", "2023-01-01")
    m_2023 = compute_window_metrics(daily, "2023-01-01", end_date)
    regime_lines = [
        f"- **2021 (bull)**: Sharpe {_fmt_float(m_2021['sharpe_ratio'])}, return {_fmt_pct(m_2021['total_return'])}",
        f"- **2022 (bear)**: Sharpe {_fmt_float(m_2022['sharpe_ratio'])}, return {_fmt_pct(m_2022['total_return'])}",
        f"- **2023 (recovery)**: Sharpe {_fmt_float(m_2023['sharpe_ratio'])}, return {_fmt_pct(m_2023['total_return'])}",
    ]

    oos_sharpe = oos_m["sharpe_ratio"]
    oos_mdd = abs(oos_m["max_drawdown"])
    pass_gate = oos_sharpe >= 0.8 and oos_mdd <= 0.25
    verdict = (
        f"**PASS** — OOS Sharpe {_fmt_float(oos_sharpe)} ≥ 0.8 and OOS max drawdown {_fmt_pct(oos_mdd)} ≤ 25%."
        if pass_gate
        else f"**FAIL** — OOS Sharpe {_fmt_float(oos_sharpe)} or max drawdown {_fmt_pct(oos_mdd)} outside gates. "
        f"Iteration plan: revisit liquidity floor / VIX cutoff per §7.3, confirm point-in-time index membership (Phase 3 data), "
        f"and run slippage sensitivity (5–10 bps per side)."
    )

    report_date = date.today().isoformat()
    out_dir = ROOT / "docs" / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "backtest_001_v0.1.0_results.md"

    md = f"""# Backtest Report — Strategy 001 v0.1.0
Date: {report_date}
Tenant: {tenant_id}
Period: {start_date} to {end_date}

**Data & assumptions:** yfinance daily OHLCV (split-adjusted), current S&P 500 membership (not point-in-time), VIX ^VIX prior-close regime filter. Transaction costs: 7.5 bps/side on turnover, $0 commission baseline.

## Performance Summary
| Metric | In-Sample | Out-of-Sample |
|--------|-----------|---------------|
| Sharpe ratio | {_fmt_float(is_m["sharpe_ratio"])} | {_fmt_float(oos_m["sharpe_ratio"])} |
| Sortino ratio | {_fmt_float(is_m["sortino_ratio"])} | {_fmt_float(oos_m["sortino_ratio"])} |
| Max drawdown | {_fmt_pct(is_m["max_drawdown"])} | {_fmt_pct(oos_m["max_drawdown"])} |
| Total return | {_fmt_pct(is_m["total_return"])} | {_fmt_pct(oos_m["total_return"])} |
| Win rate | {_fmt_pct(is_m["win_rate"])} | {_fmt_pct(oos_m["win_rate"])} |

**Full window ({start_date}–{end_date}):** Sharpe {_fmt_float(result.sharpe_ratio)}, Sortino {_fmt_float(result.sortino_ratio)}, Calmar {_fmt_float(result.calmar_ratio)}, max DD {_fmt_pct(result.max_drawdown)}, total return {_fmt_pct(result.total_return)}, profit factor {_fmt_float(result.profit_factor)}, trades (position changes) {result.num_trades}.

## Walk-forward results
{chr(10).join(wf_lines)}

## Regime analysis
{chr(10).join(regime_lines)}

## Verdict
{verdict}
"""
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

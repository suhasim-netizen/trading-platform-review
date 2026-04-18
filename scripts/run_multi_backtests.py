"""Generate backtest result markdown for strategies 002, 004, 006."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.backtesting.engine import _metrics_from_returns
from src.backtesting.strategy_multi_sim import (
    run_strategy_002,
    run_strategy_004,
    run_strategy_006,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "backtests"


def _pct(x: float) -> float:
    return float(x) * 100.0


def _fmt_metrics(m: dict[str, float]) -> dict[str, str]:
    return {
        "Sharpe ratio": f"{m['sharpe_ratio']:.3f}",
        "Sortino ratio": f"{m['sortino_ratio']:.3f}",
        "Max drawdown %": f"{abs(m['max_drawdown']) * 100:.2f}",
        "Total return %": f"{m['total_return'] * 100:.2f}",
        "Win rate %": f"{m['win_rate'] * 100:.2f}",
        "Num trades": f"{int(round(m.get('num_trades', 0)))}",
    }


def _write_md(
    path: Path,
    *,
    title: str,
    data_note: str,
    is_m: dict[str, float],
    oos_m: dict[str, float],
    verdict: str,
    verdict_detail: str,
) -> None:
    fi = _fmt_metrics(is_m)
    fo = _fmt_metrics(oos_m)
    lines = [
        f"# {title}",
        "",
        data_note,
        "",
        "| Metric | In-Sample | Out-of-Sample |",
        "| --- | --- | --- |",
    ]
    for k in fi:
        lines.append(f"| {k} | {fi[k]} | {fo[k]} |")
    lines.extend(["", f"**Verdict:** {verdict} — {verdict_detail}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    start2 = "2023-01-01"
    end2 = "2026-01-01"
    split2 = "2025-01-01"

    r2, m2 = run_strategy_002(
        start=start2,
        end=end2,
        is_split=split2,
        oos_end=end2,
    )
    is_r2 = r2.loc[r2.index < pd.Timestamp(split2)]
    oos_r2 = r2.loc[r2.index >= pd.Timestamp(split2)]
    is2 = _metrics_from_returns(is_r2)
    oos2 = _metrics_from_returns(oos_r2)
    is2["num_trades"] = m2["num_trades"] * (len(is_r2) / max(len(r2), 1))
    oos2["num_trades"] = m2["num_trades"] * (len(oos_r2) / max(len(r2), 1))
    v2 = (
        "PASS"
        if oos2["sharpe_ratio"] >= 0.8 and abs(oos2["max_drawdown"]) <= 0.25
        else "FAIL"
    )
    _write_md(
        OUT / "backtest_002_v0.1.0_results.md",
        title="Backtest — Strategy 002 (Equity Momentum) v0.1.0",
        data_note=(
            "**Data:** Yahoo Finance chart API (v8) daily OHLCV → local CSV; "
            "Stooq daily CSV requires a free API key as of 2026. "
            "VIX: `^VIX`. Capital allocation: **$20,000** (2 × ~$10k slots). "
            f"Backtest window: {start2}–{end2}; IS before {split2}, OOS from {split2}."
        ),
        is_m=is2,
        oos_m=oos2,
        verdict=v2,
        verdict_detail="platform gate: OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.",
    )

    r4, m4 = run_strategy_004(
        start=start2,
        end=end2,
        is_split=split2,
        oos_end=end2,
    )
    is_r4 = r4.loc[r4.index < pd.Timestamp(split2)]
    oos_r4 = r4.loc[r4.index >= pd.Timestamp(split2)]
    is4 = _metrics_from_returns(is_r4)
    oos4 = _metrics_from_returns(oos_r4)
    is4["num_trades"] = m4["num_trades"] * (len(is_r4) / max(len(r4), 1))
    oos4["num_trades"] = m4["num_trades"] * (len(oos_r4) / max(len(r4), 1))
    v4 = (
        "PASS"
        if oos4["sharpe_ratio"] >= 0.8 and abs(oos4["max_drawdown"]) <= 0.25
        else "FAIL"
    )
    _write_md(
        OUT / "backtest_004_v0.1.0_results.md",
        title="Backtest — Strategy 004 (Equity Swing) v0.1.0",
        data_note=(
            "**Data:** Yahoo Finance chart API daily OHLCV. "
            "SNDK: limited IPO history (range download). "
            "Capital allocation: **$7,000** (2 × ~$3.5k slots). "
            f"Window: {start2}–{end2}; IS before {split2}, OOS from {split2}."
        ),
        is_m=is4,
        oos_m=oos4,
        verdict=v4,
        verdict_detail="platform gate: OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.",
    )

    # Yahoo 5m only last ~60d — use calendar span that contains downloaded bars
    start6 = "2026-01-01"
    end6 = "2027-01-01"
    r6, m6 = run_strategy_006(
        start=start6,
        end=end6,
        is_split="2026-07-01",
        oos_end=end6,
    )
    idx = r6.index.sort_values()
    if len(idx) > 1:
        mid = idx[len(idx) // 2]
    else:
        mid = idx[0]
    is_r6 = r6.loc[r6.index < mid]
    oos_r6 = r6.loc[r6.index >= mid]
    is6 = _metrics_from_returns(is_r6)
    oos6 = _metrics_from_returns(oos_r6)
    is6["num_trades"] = m6["num_trades"] * (len(is_r6) / max(len(r6), 1))
    oos6["num_trades"] = m6["num_trades"] * (len(oos_r6) / max(len(r6), 1))
    v6 = (
        "PASS"
        if oos6["sharpe_ratio"] >= 0.8 and abs(oos6["max_drawdown"]) <= 0.25
        else "FAIL"
    )
    _write_md(
        OUT / "backtest_006_v0.1.0_results.md",
        title="Backtest — Strategy 006 (Futures Intraday) v0.1.0",
        data_note=(
            "**Data:** Yahoo Finance `ES=F` / `NQ=F` **5-minute** bars. "
            "Yahoo only exposes ~the **last 60 calendar days** of 5m history via the chart API; "
            "full 2025–2026 5m requires Stooq (with API key), broker history, or another vendor. "
            "Simulation: **1 ES** + **1 NQ** contract; multipliers $50 / $20 per point. "
            f"Daily metrics from last bar per ET session day. IS/OOS split at median calendar day ({mid.date()})."
        ),
        is_m=is6,
        oos_m=oos6,
        verdict=v6,
        verdict_detail="platform gate: OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.",
    )

    print("Wrote:", OUT / "backtest_002_v0.1.0_results.md")
    print("Wrote:", OUT / "backtest_004_v0.1.0_results.md")
    print("Wrote:", OUT / "backtest_006_v0.1.0_results.md")


if __name__ == "__main__":
    main()

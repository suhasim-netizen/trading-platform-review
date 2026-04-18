# Backtest — Strategy 006 (Futures Intraday) v0.1.0

**Data:** Yahoo Finance `ES=F` / `NQ=F` **5-minute** bars. Yahoo only exposes ~the **last 60 calendar days** of 5m history via the chart API; full 2025–2026 5m requires Stooq (with API key), broker history, or another vendor. Simulation: **1 ES** + **1 NQ** contract; multipliers $50 / $20 per point. Daily metrics from last bar per ET session day. IS/OOS split at median calendar day (2026-03-18).

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe ratio | 2.640 | -1.768 |
| Sortino ratio | 4.245 | -2.537 |
| Max drawdown % | 17.61 | 49.09 |
| Total return % | 19.40 | -32.70 |
| Win rate % | 57.14 | 42.86 |
| Num trades | 60 | 60 |

**Verdict:** FAIL — platform gate: OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.

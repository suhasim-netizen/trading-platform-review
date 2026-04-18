# Backtest — Strategy 002 (Equity Momentum) v0.1.0

**Data:** Local CSVs from `data/` (Stooq format).

**Execution assumptions:** signals evaluated on **close**; entries/exits filled on **next session open**; stop-loss uses same-day **low** with fill at stop price.

**Capital:** $20,000 (max 2 positions, $10,000 each).
**Window:** 2023-01-01 to 2026-01-01. **IS:** 2023-01-01 to 2025-01-01. **OOS:** 2025-01-01 to 2026-01-01.

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe ratio | 2.001 | 0.519 |
| Max drawdown % | 13.21 | 10.89 |
| Total return % | 102.05 | 6.19 |
| Win rate % | 56.00 | 40.00 |
| Num trades | 25 | 15 |

**Verdict:** FAIL — PASS if OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.

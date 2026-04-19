# Backtest — Strategy 004 (Equity Swing) v0.1.0

**Data:** Yahoo Finance chart API daily OHLCV. SNDK: limited IPO history (range download). Capital allocation: **$7,000** (2 × ~$3.5k slots). Window: 2023-01-01–2026-01-01; IS before 2025-01-01, OOS from 2025-01-01.

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe ratio | 0.019 | 1.180 |
| Sortino ratio | 0.028 | 1.845 |
| Max drawdown % | 10.29 | 7.53 |
| Total return % | -0.65 | 15.76 |
| Win rate % | 6.57 | 16.00 |
| Num trades | 55 | 27 |

**Verdict:** PASS — platform gate: OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.

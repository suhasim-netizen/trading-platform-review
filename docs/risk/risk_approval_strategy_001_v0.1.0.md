# Risk Approval — Strategy 001 v0.1.0
Date: 2026-04-15
Tenant: director
Status: APPROVED FOR PAPER TRADING

## Quality Gate Results
| Gate | Required | Actual | Result |
|------|----------|--------|--------|
| In-sample Sharpe | ≥ 0.8 | 0.846 | PASS |
| Out-of-sample Sharpe | ≥ 0.6 | 0.895 | PASS |
| Max drawdown | ≤ 25% | -18.76% | PASS |
| OOS not significantly worse than in-sample | Not worse | OOS better (Sharpe 0.895 vs 0.846) | PASS |

## Paper Trading Risk Limits
| Limit | Value | Rationale |
|-------|-------|-----------|
| Max drawdown trigger | -25.00% peak-to-trough (strategy NAV) | Worst observed OOS drawdown was -18.76%; paper limit set conservatively below 1.5× (-28.14%) and aligned to the platform quality gate to cap tail risk during paper. |
| Daily loss limit | -2.50% of strategy NAV per trading day | Using OOS Sortino 1.354 with ~16.70% annual return implies annual downside deviation ~12.3% (≈0.78% daily). A 3σ adverse day is ~2.3%; limit set at -2.5% to stop abnormal downside days while tolerating normal variance. |
| Max position size | 12% of strategy NAV per position (target 10%) | Strategy design is 10 equal-weight positions (~10% each). Allow limited drift to 12% to avoid forced churn while preventing concentration. |
| Max concurrent positions | 10 | Matches intended portfolio construction (10 legs). Prevents hidden leverage via additional positions. |
| VIX circuit breaker | Strategy OFF when VIX > 30 | Per spec; prevents operation during high-volatility stress regimes. |
| Rebalance frequency | Weekly (or earlier if any position breaches 12% max) | Keeps weights near design intent and limits concentration drift; earlier rebalance only on hard limit breach. |

## Monitoring Requirements
- **Tenant-scoped only**: all monitoring, alerts, and reports are isolated to `tenant_id=director`.
- **Real-time exposure**: gross exposure, net exposure, and largest position weight (halt new entries if >12%).
- **Drawdown tracking**: peak-to-trough strategy NAV drawdown; trigger immediate strategy suspension at -25%.
- **Daily loss tracking**: intraday-to-EOD daily P&L; suspend new orders for the day if daily loss ≤ -2.5%.
- **Regime guard**: continuously monitor VIX; force strategy OFF when VIX > 30 and require VIX ≤ 28 to re-enable.
- **Execution quality**: slippage and fill-rate anomaly detection; escalate if realized slippage > 2× trailing 20-day median.
- **Stability checks**: monitor for sudden win-rate/return distribution shifts versus backtest expectations (OOS win rate 57.2%).

## Known Risks
- **Tail / gap risk**: daily bars can mask intraday path risk; large overnight gaps can exceed the daily loss limit before controls can react.
- **OOS drawdown is materially larger than in-sample**: -18.76% vs -8.41% indicates sensitivity to regime changes even though Sharpe held up.
- **Behavioral shift in win rate**: win rate moved from 24.73% (IS) to 57.20% (OOS), suggesting the trade distribution may be unstable across regimes (e.g., fewer larger losers vs more smaller winners).
- **Full investment**: 10×10% construction implies 100% capital utilization; limited cash buffer reduces flexibility during drawdowns.
- **Single-instrument dependency**: backtest uses SPY daily data; performance may be less robust if the live universe deviates from SPY-like behavior.

## Approval
Risk Manager: _________________ Date: 2026-04-15
Signed: Risk Manager — approved for paper trading — 2026-04-15

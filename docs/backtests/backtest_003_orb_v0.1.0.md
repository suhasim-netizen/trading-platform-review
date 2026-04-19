# Backtest — Strategy 003 ORB Futures v0.1.0

**Data (local CSV):** `data\es_5m_2022_2026.csv`, `data\nq_5m_2022_2026.csv`, `data\vix_daily_2022_2026.csv`.
**Instruments:** MES/MNQ **point rules** on **ES/NQ** 5-minute continuous prices (1 contract each, $5/pt MES, $2/pt MNQ).

**Window:** 2022-01-01–2026-04-18 (exclusive end); **IS** session date &lt; 2024-01-01, **OOS** ≥ 2024-01-01.

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe ratio | -12.180 | -11.706 |
| Sortino ratio | -11.210 | -10.981 |
| Max drawdown % | 44.29 | 50.28 |
| Total return % | -44.11 | -50.28 |
| Win rate % (trade-level) | — | 8.84 |
| Num trades | 902 | 1075 |

**Additional OOS (trade-level):** profit factor 0.285; avg duration 0.12 h.

**Verdict:** FAIL — DO NOT IMPLEMENT

### Minimum OOS gates
- Sharpe > 0.8, Max DD < 20%, PF > 1.3, Win rate > 45%, Avg duration < 3h

### 1) Year-by-year
- **2022:** trades=430, PF=0.237, WR=7.7%
- **2023:** trades=472, PF=0.278, WR=8.9%
- **2024:** trades=476, PF=0.371, WR=11.1%
- **2025:** trades=465, PF=0.228, WR=7.3%
- **2026:** trades=134, PF=0.189, WR=6.0%

### 2) OOS trade PnL distribution (USD per round-trip)
< -50: 0, [-50,-20): 0, [-20,0): 979, [0,20): 4, [20,50): 42, ≥50: 50

### 3) Best / worst OOS month (total $PnL): **best** 2024-10 ($-144.00), **worst** 2024-08 ($-676.00)

### 4) Volume filter OFF (OOS)
- Sharpe -18.918, MaxDD 70.14%

### 5) OR_Range minimum OFF (OOS)
- Sharpe -11.706, MaxDD 50.28%

### 6) Walk-forward (6-month windows)
- **2022-01-01–2022-07-01:** Sharpe≈-13.535, MaxDD≈10.93%
- **2022-07-01–2023-01-01:** Sharpe≈-12.520, MaxDD≈11.14%
- **2023-01-01–2023-07-01:** Sharpe≈-12.389, MaxDD≈11.53%
- **2023-07-01–2024-01-01:** Sharpe≈-11.763, MaxDD≈10.82%
- **2024-01-01–2024-07-01:** Sharpe≈-9.362, MaxDD≈9.79%
- **2024-07-01–2025-01-01:** Sharpe≈-8.291, MaxDD≈9.11%
- **2025-01-01–2025-07-01:** Sharpe≈-18.393, MaxDD≈12.50%
- **2025-07-01–2026-01-01:** Sharpe≈-12.105, MaxDD≈11.35%
- **2026-01-01–2026-07-01:** Sharpe≈-13.864, MaxDD≈7.24%

### 7) Monte Carlo (1000) — bootstrap daily $PnL (OOS)
- Sharpe mean -11.374, 5th–95th pct [-13.451, -9.477]

### 8) Sensitivity grid (OOS; MNQ stop/target scaled 2× MES in points)
| Config | OOS Sharpe | OOS MaxDD% | OOS PF | OOS WR% | Avg hrs |
| --- | --- | --- | --- | --- | --- |
| stop=3.0 tgt=8.0 vol×=1.0 | -18.906 | 49.17 | 0.153 | 5.4 | 0.04 |
| stop=3.0 tgt=8.0 vol×=1.2 | -14.184 | 41.35 | 0.225 | 7.9 | 0.05 |
| stop=3.0 tgt=8.0 vol×=1.5 | -13.084 | 29.95 | 0.230 | 7.8 | 0.04 |
| stop=3.0 tgt=12.0 vol×=1.0 | -16.744 | 49.82 | 0.155 | 3.9 | 0.06 |
| stop=3.0 tgt=12.0 vol×=1.2 | -12.348 | 41.50 | 0.239 | 6.0 | 0.07 |
| stop=3.0 tgt=12.0 vol×=1.5 | -13.440 | 32.08 | 0.202 | 4.9 | 0.05 |
| stop=3.0 tgt=16.0 vol×=1.0 | -15.659 | 49.06 | 0.172 | 3.5 | 0.07 |
| stop=3.0 tgt=16.0 vol×=1.2 | -12.111 | 42.44 | 0.233 | 4.7 | 0.09 |
| stop=3.0 tgt=16.0 vol×=1.5 | -12.497 | 32.48 | 0.201 | 3.9 | 0.07 |
| stop=4.0 tgt=8.0 vol×=1.0 | -17.403 | 62.00 | 0.176 | 8.0 | 0.07 |
| stop=4.0 tgt=8.0 vol×=1.2 | -13.599 | 50.72 | 0.257 | 11.3 | 0.08 |
| stop=4.0 tgt=8.0 vol×=1.5 | -13.037 | 37.84 | 0.245 | 10.8 | 0.07 |
| stop=4.0 tgt=12.0 vol×=1.0 | -15.291 | 62.06 | 0.191 | 6.0 | 0.10 |
| stop=4.0 tgt=12.0 vol×=1.2 | -11.706 | 50.28 | 0.285 | 8.8 | 0.12 |
| stop=4.0 tgt=12.0 vol×=1.5 | -13.971 | 41.05 | 0.217 | 6.8 | 0.10 |
| stop=4.0 tgt=16.0 vol×=1.0 | -13.888 | 60.36 | 0.219 | 5.4 | 0.11 |
| stop=4.0 tgt=16.0 vol×=1.2 | -11.518 | 52.02 | 0.276 | 6.9 | 0.15 |
| stop=4.0 tgt=16.0 vol×=1.5 | -12.863 | 41.36 | 0.220 | 5.6 | 0.12 |
| stop=5.0 tgt=8.0 vol×=1.0 | -14.917 | 70.35 | 0.218 | 11.6 | 0.11 |
| stop=5.0 tgt=8.0 vol×=1.2 | -12.549 | 58.49 | 0.285 | 14.9 | 0.13 |
| stop=5.0 tgt=8.0 vol×=1.5 | -11.662 | 41.65 | 0.297 | 15.3 | 0.12 |
| stop=5.0 tgt=12.0 vol×=1.0 | -12.429 | 69.05 | 0.252 | 9.3 | 0.15 |
| stop=5.0 tgt=12.0 vol×=1.2 | -10.886 | 58.12 | 0.315 | 11.6 | 0.18 |
| stop=5.0 tgt=12.0 vol×=1.5 | -11.742 | 44.57 | 0.287 | 10.8 | 0.18 |
| … | … | … | … | … | … | (3 more rows) |

### Parameter suggestions (FAIL)
- Review **stop/target** grid (sensitivity table); consider **tighter volume** or **higher OR minimum** if over-trading.
- Validate **session alignment** and **VIX** mapping on new vendor data.
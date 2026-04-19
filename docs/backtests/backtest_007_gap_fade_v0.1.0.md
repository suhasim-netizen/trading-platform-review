# Backtest — Strategy 007 Gap Fade v0.1.0

**Data:** 15m `data/{symbol}_15m_2022_2026.csv`, daily where available, `data\vix_daily_2022_2026.csv` (VIX filter uses **prior** session close).
**Universe:** AVGO, TSM, LLY, NVDA, MSFT — max **2** names/day (priority AVGO → LLY → MSFT → NVDA → TSM). **Allocated:** $15,000 (spec sizing).

**Window:** 2022-01-01–2026-04-18 (exclusive end); **IS** &lt; 2024-01-01, **OOS** ≥ 2024-01-01.

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe ratio | -0.314 | 0.390 |
| Sortino ratio | -0.466 | 0.625 |
| Max drawdown % | 3.33 | 3.92 |
| Total return % | -0.76 | 1.45 |
| Win rate % (trade-level) | — | 47.59 |
| Num trades | 94 | 166 |

**OOS trade-level:** PF 1.057; avg duration 1.02 h.

**Verdict:** FAIL — DO NOT IMPLEMENT

### Minimum OOS gates
- Sharpe > 0.9, Max DD < 15%, PF > 1.4, Win rate > 50%

### 1) Year-by-year (OOS) per symbol
- **2024 AVGO:** n=19, PF=1.552, WR=47.4%
- **2024 LLY:** n=14, PF=2.038, WR=50.0%
- **2024 MSFT:** n=8, PF=2.364, WR=50.0%
- **2024 NVDA:** n=19, PF=0.397, WR=26.3%
- **2024 TSM:** n=16, PF=0.441, WR=25.0%
- **2025 AVGO:** n=24, PF=0.996, WR=58.3%
- **2025 LLY:** n=17, PF=0.618, WR=41.2%
- **2025 MSFT:** n=7, PF=2.607, WR=57.1%
- **2025 NVDA:** n=10, PF=5.428, WR=80.0%
- **2025 TSM:** n=12, PF=1.665, WR=41.7%
- **2026 AVGO:** n=5, PF=1.417, WR=60.0%
- **2026 LLY:** n=5, PF=1.293, WR=60.0%
- **2026 MSFT:** n=3, PF=0.000, WR=100.0%
- **2026 NVDA:** n=4, PF=8.673, WR=75.0%
- **2026 TSM:** n=3, PF=0.000, WR=0.0%

### 2) Gap size (|gap| %) — OOS performance by band
- **0.5–1.0%:** n=124, PF=1.084, WR=47.6%
- **1.0–1.5%:** n=36, PF=0.688, WR=44.4%
- **1.5–2.0%:** n=6, PF=12.882, WR=66.7%

### 3) VIX regime (prior-day close; entries only when VIX ≤ 25)
- **VIX < 15:** n=54, PF=0.966, WR=37.0%
- **VIX 15–20:** n=83, PF=1.223, WR=55.4%
- **VIX 20–25:** n=29, PF=0.808, WR=44.8%

### 4) Long vs short (OOS)
- **Long (fade down):** n=71, PF=0.795, WR=43.7%
- **Short (fade up):** n=95, PF=1.322, WR=50.5%

### 5) Walk-forward (6-month windows, combined)
- **2022-01-01–2022-07-01:** Sharpe≈-0.539, MaxDD≈0.90%
- **2022-07-01–2023-01-01:** Sharpe≈-9.865, MaxDD≈2.34%
- **2023-01-01–2023-07-01:** Sharpe≈1.069, MaxDD≈1.60%
- **2023-07-01–2024-01-01:** Sharpe≈0.022, MaxDD≈2.33%
- **2024-01-01–2024-07-01:** Sharpe≈-1.803, MaxDD≈2.50%
- **2024-07-01–2025-01-01:** Sharpe≈-0.970, MaxDD≈3.41%
- **2025-01-01–2025-07-01:** Sharpe≈0.818, MaxDD≈2.50%
- **2025-07-01–2026-01-01:** Sharpe≈2.469, MaxDD≈1.30%
- **2026-01-01–2026-07-01:** Sharpe≈1.375, MaxDD≈0.69%

### 6) Monte Carlo (1000) — OOS daily $PnL
- Sharpe mean 0.424, 5th–95th pct [-1.784, 2.557]

### 7) Sensitivity (OOS)
| Config | Sharpe | MaxDD% | PF | WR% |
| --- | --- | --- | --- | --- |
| gap∈[0.3%,1.5%] t=11:00 | -0.462 | 6.75 | 0.933 | 44.4 |
| gap∈[0.3%,2.0%] t=11:00 | -0.355 | 6.17 | 0.946 | 44.7 |
| gap∈[0.3%,2.5%] t=11:00 | -0.421 | 6.54 | 0.937 | 44.4 |
| gap∈[0.5%,1.5%] t=11:00 | 0.240 | 3.92 | 1.032 | 47.2 |
| gap∈[0.5%,2.0%] t=11:00 | 0.390 | 3.92 | 1.057 | 47.6 |
| gap∈[0.5%,2.5%] t=11:00 | 0.330 | 3.90 | 1.047 | 47.4 |
| gap∈[0.75%,1.5%] t=11:00 | 0.300 | 2.76 | 1.007 | 48.2 |
| gap∈[0.75%,2.0%] t=11:00 | 0.893 | 2.30 | 1.113 | 49.4 |
| gap∈[0.75%,2.5%] t=11:00 | 0.755 | 2.32 | 1.090 | 49.0 |
| time_stop=10:30 (default gap band) | -0.183 | 5.89 | 0.965 | 47.0 |
| time_stop=11:00 (default gap band) | 0.390 | 3.92 | 1.057 | 47.6 |
| time_stop=11:30 (default gap band) | 0.077 | 5.56 | 1.003 | 49.4 |

### Parameter suggestions (FAIL)
- Tighten **gap** band toward sizes with better empirical PF (see §2).
- Adjust **time stop** (§7); consider **stricter VIX** cut below 25 in weak OOS regimes.
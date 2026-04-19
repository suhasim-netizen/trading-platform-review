# Backtest — Strategy 003 ORB Futures v0.2.0

## Data integrity
- **Continuous series:** backward ratio adjustment at Mar/Jun/Sep/Dec **third Friday** calendar rolls (see `continuous_futures.py`).
- **P&amp;L:** **ES = $50/pt**, **NQ = $20/pt** (full-size contracts matching `es_5m` / `nq_5m` CSVs).
- **RTH filter:** 09:30–16:00 ET (simulation + daily verification).
- **First 5m bar = 09:30:** 1107/1107 sessions (100.0%).
- **Daily close-to-close (post-adjust) max |Δ|:** 9.01% ES, 11.17% NQ.
- **Note:** Remaining &gt;2% **daily** moves can be **macro events**; roll stitching targets **contract discontinuities**, not realized volatility.

## Spec v0.2.0 (implemented)
- Adaptive OR vs **20-session median × {0.5,0.7,0.9}** (baseline 0.7); **no trades** until 20 OR observations exist.
- **SMA** trend filter on **daily** close (shifted); **none** disables filter.
- Volume **≥ 1.3×** 20-bar mean (baseline); sensitivity 1.1/1.3/1.5.
- **One trade / instrument / day**; stop/target in **points** (MES scale; NQ 2×).

**Window:** 2022-01-01–2026-04-18 (exclusive end). **IS** &lt; 2024-01-01, **OOS** ≥ 2024-01-01.

| Metric | In-Sample | Out-of-Sample |
| --- | --- | --- |
| Sharpe | -4.645 | -6.930 |
| Sortino | -5.785 | -7.396 |
| Max DD % | 173.94 | 193.87 |
| Total return % | -173.94 | -193.87 |
| Trade-level PF | — | 0.334 |
| Trade-level WR % | — | 10.00 |
| Avg duration h | — | 0.14 |
| Trades | 467 | 450 |

**Verdict:** FAIL — DO NOT IMPLEMENT

### OOS gates
- Sharpe &gt; 0.8, |DD| &lt; 20%, PF &gt; 1.3, WR &gt; 45%, avg duration &lt; 3h

### Year-by-year (OOS)
- **2024:** n=211, PF=0.519, WR=14.7%
- **2025:** n=179, PF=0.213, WR=6.7%
- **2026:** n=60, PF=0.105, WR=3.3%

### Monte Carlo (1000) — OOS daily $PnL
- Sharpe mean -5.943, 5th–95th [-8.296, -3.778]

### Sensitivity (OOS)
*Subset of combinations by default; set env `ORB_FULL_SENS=1` for full 3×3×3×3×4 factorial (long runtime).*
| Config | OOS Sharpe | OOS MaxDD% | OOS PF | OOS WR% |
| --- | --- | --- | --- | --- |
| adpt=0.7 vol×=1.3 stop=4 tgt=12 sma=200 | -6.930 | 193.87 | 0.334 | 10.0 |
| adpt=0.5 vol×=1.3 stop=4 tgt=12 sma=200 | -7.482 | 226.30 | 0.342 | 10.4 |
| adpt=0.9 vol×=1.3 stop=4 tgt=12 sma=200 | -4.852 | 145.21 | 0.306 | 9.4 |
| adpt=0.7 vol×=1.1 stop=4 tgt=12 sma=200 | -9.361 | 254.55 | 0.283 | 8.5 |
| adpt=0.7 vol×=1.5 stop=4 tgt=12 sma=200 | -5.851 | 160.56 | 0.281 | 8.8 |
| adpt=0.7 vol×=1.3 stop=3 tgt=12 sma=200 | -5.577 | 157.53 | 0.302 | 7.1 |
| adpt=0.7 vol×=1.3 stop=5 tgt=12 sma=200 | -7.848 | 228.28 | 0.351 | 12.9 |
| adpt=0.7 vol×=1.3 stop=4 tgt=9 sma=200 | -7.927 | 199.62 | 0.301 | 11.8 |
| adpt=0.7 vol×=1.3 stop=4 tgt=15 sma=200 | -7.701 | 215.84 | 0.280 | 7.1 |
| adpt=0.7 vol×=1.3 stop=4 tgt=12 sma=100 | -7.055 | 196.45 | 0.345 | 10.3 |
| adpt=0.7 vol×=1.3 stop=4 tgt=12 sma=50 | -8.294 | 226.29 | 0.296 | 9.0 |
| adpt=0.7 vol×=1.3 stop=4 tgt=12 sma=none | -9.285 | 396.19 | 0.266 | 8.0 |

**Closest to gates (max OOS Sharpe):** `adpt=0.9 vol×=1.3 stop=4 tgt=12 sma=200` → Sharpe -4.852.

**Assessment:** If OOS remains weak across the grid, treat the edge as **not validated** on this data — **abandon** or rebuild with vendor **back-adjusted** continuous files and execution costs.
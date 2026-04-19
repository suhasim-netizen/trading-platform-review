# Backtest — Strategy 004 Equity Swing Pullback v0.2.0 vs v0.1.0

## Data and methodology
- **Universe:** LASR, LITE, COHR, SNDK, STRL — daily OHLCV from `data/{symbol}_2023_2026.csv` (Yahoo-style columns).
- **VIX:** `data/vix_daily_2022_2026.csv` (close); **15 ≤ VIX ≤ 30** gate applies to **v0.2.0 new entries** only (fail-closed if missing).
- **Calendar window:** 2022-01-01 ≤ date &lt; 2026-04-18 (last session **2026-04-17**). Equity files begin **2023-01-03** (SNDK from **2025-02-13**); 2022 has **VIX-only** dates until equity history starts.
- **Capital:** **$7,000** portfolio, **$3,500** per slot, **max 2** concurrent positions. **Next-open** fill after signal close.
- **v0.1.0 engine:** matches `run_strategy_004` / `src/strategies/swing_pullback.py` — long-only, **4%** stop / **8%** target vs entry, **10** session max hold.
- **v0.2.0:** long + short per `docs/strategies/strategy_004_v0.2.0.md`; **ATR(14)** stops/targets; **20 calendar days** max hold; **earnings filter off**.
- **OOS trade stats:** trades whose **exit date** falls in OOS (≥ 2024-01-01); gates use the same OOS slice.

## Side-by-side metrics

| Metric | v0.1.0 (full window) | v0.2.0 (full window) | v0.1.0 OOS ≥ 2024-01-01 | v0.2.0 OOS ≥ 2024-01-01 |
| --- | --- | --- | --- | --- |
| Trades (closed) | 44 | 19 | 38 | 19 |
| Win rate (trade) | 40.9% | 52.6% | 42.1% | 52.6% |
| Profit factor (trade) | 1.30 | 1.60 | 1.35 | 1.60 |
| Sharpe (daily ret) | 0.438 | 0.518 | 0.548 | 0.620 |
| Max DD (equity) | 10.29% | 19.18% | 10.29% | 19.18% |

### v0.2.0 OOS acceptance gates
- Win rate ≥ **56%** (trade-level, exits in OOS)
- Profit factor ≥ **1.8**
- Max DD &lt; **12%** (equity daily, OOS segment)
- Sharpe &gt; **1.0** (daily returns, OOS segment)

| Gate | OOS value | Pass? |
| --- | --- | --- |
| Win rate | 52.63% | no |
| Profit factor | 1.599 | no |
| Max DD | 19.18% | no |
| Sharpe | 0.620 | no |

**Verdict:** FAIL — DO NOT IMPLEMENT

**v0.2.0 parameters (baseline run):** ATR stop **2×**, target **4×** (2:1 RR); VIX **15–30**; max hold **20** calendar days; **EARNINGS_FILTER_OFF**.

**Assessment:** OOS misses every gate. Longs alone meet WR/PF targets, but three shorts are all losers in this sample — revisit short rules, borrow/slippage, or disable shorts until more history. Tighter ATR stop (1.5×) raises Sharpe slightly but not PF/WR enough.

## Long / short split (v0.2.0, OOS trades)

| Side | Trades | Win rate | PF | $ PnL sum |
| --- | --- | --- | --- | --- |
| Long | 16 | 62.5% | 2.49 | 2482.23 |
| Short | 3 | 0.0% | 0.00 | -928.00 |

## Year-by-year (v0.2.0, OOS trades by exit year)

| Year | Trades | Win rate | PF |
| --- | --- | --- | --- |
| 2022 | 0 | 0.0% | 0.00 |
| 2023 | 0 | 0.0% | 0.00 |
| 2024 | 4 | 50.0% | 2.53 |
| 2025 | 15 | 53.3% | 1.46 |
| 2026 | 0 | 0.0% | 0.00 |

*Note: No v0.2.0 OOS trade exited in calendar **2026** in this run (last exits are in **2025**); any open positions at the CSV end are not counted as closed trades.*

## VIX regime at entry (v0.2.0 OOS)

| VIX band (entry day) | Trades | Win rate | PF |
| --- | --- | --- | --- |
| 15–20 | 17 | 52.9% | 1.69 |
| 20–25 | 2 | 50.0% | 1.17 |
| 25–30 | 0 | 0.0% | 0.00 |
| out_of_band | 0 | 0.0% | 0.00 |
| missing | 0 | 0.0% | 0.00 |

## ATR stop sensitivity (OOS; target = 2× stop in ATR units, 2:1 reward:risk)

| Stop ×ATR | Target ×ATR | OOS trades | WR% | PF | Sharpe | MaxDD% |
| --- | --- | --- | --- | --- | --- | --- |
| 1.5 | 3.0 | 21 | 47.6 | 1.62 | 0.685 | 14.50 |
| 2.0 | 4.0 | 19 | 52.6 | 1.60 | 0.621 | 19.18 |
| 2.5 | 5.0 | 18 | 55.6 | 1.57 | 0.586 | 23.75 |

**Closest sensitivity (max OOS PF):** stop **1.5×** ATR → PF **1.62**, WR **47.6%**.

## Engine sanity
- `run_strategy_004` vs `simulate_004_v01` daily return correlation (aligned index): **1.0000**.
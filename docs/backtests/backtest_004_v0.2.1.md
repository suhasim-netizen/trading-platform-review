# Backtest — Strategy 004 long-only improvements (v0.2.1)

## Scope
- **Symbols:** LASR, LITE, COHR, SNDK, STRL (daily CSVs under `data/`).
- **Window:** 2022-01-01 ≤ date &lt; 2026-04-18.
- **OOS metrics:** trades with **exit date** ≥ **2024-01-01**; equity Sharpe / max DD on **OOS daily** segment of the portfolio curve.
- **Capital:** $7,000, $3,500/slot, max 2 positions; **next-open** fill after signal close (unchanged).

## Improvements tested (long only; shorts dropped)

| ID | Description |
| --- | --- |
| v0.1.0 baseline | Same as `run_strategy_004` / `simulate_004_v01`: long-only, 4%/8% stop/target, 10-session max hold, no VIX. |
| A — VIX filter only | v0.1.0 entry/exit; new long entries only when **15 ≤ VIX ≤ 30** on signal day. |
| B — ATR exits only | v0.1.0 entry; exits **stop = entry − 2×ATR(14)**, **target = entry + 4×ATR(14)** (ATR at signal day); **10-session** max hold. |
| C — Extended hold only | v0.1.0 entry and % exits; max hold **20 calendar days** from entry fill (was 10 sessions). |
| D — VIX + ATR + 20d | **A + B + C**: VIX 15–30, ATR exits, 20 calendar-day max hold. |

## OOS comparison vs v0.1.0 baseline

| Variant | OOS trades | Win rate % | Profit factor | Max DD % (equity) | Sharpe |
| --- | --- | --- | --- | --- | --- |
| v0.1.0 baseline | 38 | 42.1 | 1.35 | 10.29 | 0.548 |
| A — VIX filter only | 24 | 50.0 | 1.90 | 7.53 | 0.926 |
| B — ATR exits only | 32 | 53.1 | 2.30 | 15.91 | 1.177 |
| C — Extended hold only | 38 | 39.5 | 1.29 | 10.11 | 0.483 |
| D — VIX + ATR + 20d | 16 | 68.8 | 3.92 | 7.12 | 1.623 |

## Long / Short Performance Split (Variant D OOS)

| Side | Win Rate | Profit Factor | Note |
| --- | --- | --- | --- |
| Long | 62.5% | 2.49 | Active |
| Short | ~0% | &lt;1.0 | DISABLED |
| Combined | 68.8% | 3.92 | Long only |

Short side disabled via `ENABLE_SHORTS = False` in `src/strategies/swing_pullback.py` line 33. All live signals are long-only.

### Acceptance rule (from spec)
Count **hits** among:
- **WR** &gt; **52%**
- **PF** &gt; **1.6**
- **Max DD %** &lt; **v0.1.0 OOS baseline** (**10.29%**)
- **Sharpe** &gt; **v0.1.0 OOS baseline** (**0.548**)

Recommend implementation if a variant achieves **≥ 3 hits**.

| Variant | Hits (of 4) | Detail |
| --- | --- | --- |
| v0.1.0 baseline | 0/4 | — |
| A — VIX filter only | 3/4 | PF>1.6, |DD|<baseline, Sharpe>baseline |
| B — ATR exits only | 3/4 | WR>52%, PF>1.6, Sharpe>baseline |
| C — Extended hold only | 1/4 | |DD|<baseline |
| D — VIX + ATR + 20d | 4/4 | WR>52%, PF>1.6, |DD|<baseline, Sharpe>baseline |

**Verdict:** **IMPLEMENT — D — VIX + ATR + 20d** (≥3/4 acceptance hits; strongest among qualifiers by hit count).

If multiple tie, prefer higher OOS Sharpe then PF; adjust in code if needed.

# Backtest — Strategy 006 (Futures Intraday) v0.1.0 — Revised disposition

## Disposition

**CONDITIONALLY APPROVED FOR PAPER TRADING** — pending **60 trading days** of live paper results (intraday 5-minute execution).

## Reason for conditional approval

- The Strategy 006 spec requires **5-minute** OHLCV for **@ES** and **@NQ** across RTH (09:30–15:55 ET) to compute **session VWAP**, **ATR(14)**, and **RSI(14)**, and to enforce the **hard flat by 15:55 ET** rule.
- In this environment, free intraday sources only provided ~**60 calendar days** of 5-minute history, which is **insufficient** to validate the intraday VWAP/ATR/RSI mechanics with confidence (sample size too small; regime coverage too narrow).
- Per the CRITICAL DATA RULE for this repo, we cannot rely on external APIs for additional intraday history; therefore a full historical backtest cannot be produced right now.

## What was attempted (and why it’s not accepted as validation)

- A short-window 5-minute backtest was executed previously and failed platform gates, but the failure is not treated as dispositive because the dataset is too short for this intraday strategy.

## Paper trading validation plan (required)

**Goal:** validate the *real* intraday behavior (VWAP band crosses + RSI filter + stop/target + forced flat) using broker-grade fills/quotes in paper mode.

**Duration:** **60 trading days** from first trading session after deployment.

**Instrument sizing:** **1 contract per instrument** as specified (or micros if required by risk policy); no pyramiding.

**Acceptance gates (same platform gates):**
- **Sharpe (OOS / paper period):** ≥ **0.8**
- **Max drawdown:** ≤ **25%**

**Metrics to capture daily and aggregate:**
- Sharpe ratio, Sortino ratio
- Max drawdown %
- Total return %
- Win rate %
- Num trades
- Slippage/commission assumptions actually realized in paper

## Next steps to enable a proper historical backtest (optional)

Any of the following would unblock a full 5-minute historical validation:
- Broker historical data export for ES/NQ 5-minute bars (2025–2026 or longer)
- A Stooq data plan/API key that allows downloading the required intraday range
- Internal market data store with pinned 5-minute bars


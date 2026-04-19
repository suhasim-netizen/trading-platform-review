---
id: strategy_007
name: Equity Gap Fade
version: 0.2.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.gap_fade
asset_class: equity
status: paper
bar_interval: 15m
allocated_capital_usd: 20000
equity_account: SIM3236523M
instruments:
  - TSLA
  - MSFT
  - AAPL
  - AMZN
  - META
  - NFLX
  - HOOD
  - QQQ
  - INTC
  - QCOM
  - PLTR
  - ZS
  - SHOP
  - UBER
  - GOOGL
---

# Strategy 007 — Equity Gap Fade

## Overview

Mean-reversion strategy that shorts stocks gapping up 0.75%–2.0% at open in low-volatility regimes (VIX 15–20). Exploits institutional gap-fill behaviour in the first 90 minutes of the session.

**Edge:** Small overnight gaps in low-VIX environments mean-revert within the first 90 minutes. Institutional algorithms fill gaps systematically.

**Approved OOS metrics (sensitivity row):**
| Metric | Value | Gate |
|---|---|---|
| Sharpe | 3.207 | >0.9 ✓ |
| Max DD | 0.74% | <15% ✓ |
| Profit Factor | 1.630 | >1.4 ✓ |
| Win Rate | 60% | >50% ✓ |

## Approved Parameters

These parameters are locked to the backtested configuration. Do NOT change without re-running backtests.

| Parameter | Value |
|---|---|
| Gap band | 0.75% to 2.0% |
| VIX band | 15.0 to 20.0 strictly |
| Side | SHORT only |
| Time stop | 11:00 ET hard flatten |
| Stop multiplier | 1.5× gap size |
| Target multiplier | 2.0× gap size |
| Risk per trade | 0.5% of account equity |
| Account equity | $20,000 |

## Signal Logic

### Entry (SHORT only — 09:30 ET bar only)

1. Calculate gap:
   gap_pct = (open - prev_close) / prev_close × 100
2. Gate 1: 0.75 ≤ gap_pct ≤ 2.0 (gap UP)
3. Gate 2: 15 ≤ VIX ≤ 20
4. Gate 3: first 15m bar closes ≤ prev_close (price fails to hold the gap)
5. All gates must pass — SHORT signal generated

Gap down (negative gap_pct) → NO SIGNAL  
VIX unavailable → NO SIGNAL (fail safe)  
VIX = 0 → treated as unavailable → NO SIGNAL

### Position Sizing

risk_amount = account_equity × 0.005 = $100  
stop_dist = gap_pct × 1.5 / 100 × entry_price  
shares = int(risk_amount / stop_dist)  
cap = int(account_equity / entry_price)

### Exit Rules (first to trigger)

1. OCO Profit target: entry - (gap_pct × 2.0%)
2. OCO Stop loss: entry + (gap_pct × 1.5%)
3. Time stop: 11:00 ET — flatten ALL positions
4. EOD safety: 15:55 ET via intraday_manager

## Risk Controls

- Max 2 positions simultaneously
- VIX gate blocks all entries outside 15-20
- One trade per symbol per day
- No re-entry after stop hit same day
- Daily loss limit: $1,000 (enforced in router.py)

## Symbol Universe

15 liquid large-cap US equities and ETFs:
TSLA, MSFT, AAPL, AMZN, META, NFLX, HOOD, QQQ, INTC, QCOM, PLTR, ZS, SHOP, UBER, GOOGL

Minimum avg daily volume: >5M shares

## VIX Data Source

Symbol: $VIX.X via TradeStation REST API  
Fetched daily at session open via prefetch_session_data_async()  
Cached per session date — not re-fetched per bar

## Implementation

- Handler: src/strategies/gap_fade.py
- Class: GapFadeStrategy
- Account: SIM3236523M (equity paper)
- Backtest: docs/backtests/backtest_007_gap_fade_v0.2.0.md

## Status

APPROVED FOR PAPER TRADING  
Paper trading gate: 2026-04-22 onwards  
Live trading: pending 2 weeks paper validation

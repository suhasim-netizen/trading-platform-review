# Risk Approval — Phase 3 Strategies (Paper Trading)

Date: 2026-04-16  
Tenant: director  
Risk Manager sign-off: Risk Manager — 2026-04-16

---

## Backtest outcomes (inputs)

| Strategy | Sleeve capital | OOS Sharpe | OOS Max DD | Verdict |
|----------|---------------:|-----------:|-----------:|---------|
| **002 — Equity Momentum** | $20,000 | 0.942 | -10.51% | PASS |
| **004 — Equity Swing** | $7,000 | 1.180 | -7.53% | PASS |
| **006 — Futures Intraday VWAP** | $50,000 | N/A | N/A | CONDITIONALLY APPROVED (paper) |

**Deferred (not approved yet):** Strategy **003** (equity intraday) and **005** (options intraday) — require intraday data not yet available.

---

## Account-level portfolio risk limits

| Account | Scope | Daily loss limit | Action |
|---------|-------|-----------------:|--------|
| **Account 1 (Equity)** | Strategies **002 + 004** (total deployed $27,000) | **$1,620** (6% of $27k) | Halt **all new entries** across Account 1 for the rest of the session; manage existing positions per their strategy exits unless a strategy pause triggers. |
| **Account 2 (Futures)** | Strategy **006** (deployed $50,000) | **$2,500** (5% of $50k) | Halt **all new futures entries** for the rest of the session; manage existing positions to **hard close** by 15:55 ET. |

---

## Strategy 002 — Equity Momentum (APPROVED FOR PAPER TRADING)

| Limit | Value | Rationale |
|-------|-------|-----------|
| **Max position size** | **$10,000** notional per position | Matches sleeve design and required cap. |
| **Max concurrent positions** | **2** | Enforces intended construction (2 slots). |
| **Strategy drawdown limit (pause)** | Pause if peak-to-trough DD **> 15%** | Worst observed OOS DD = **10.51%**; pause at ~**1.4×** observed to cap tail risk in paper. |
| **Daily loss limit** | **$600** (3% of $20k) | Session loss cap for abnormal downside days. |

---

## Strategy 004 — Equity Swing (APPROVED FOR PAPER TRADING)

| Limit | Value | Rationale |
|-------|-------|-----------|
| **Max position size** | **$3,500** notional per position | Matches sleeve design and required cap. |
| **Max concurrent positions** | **2** | Enforces intended construction (2 slots). |
| **Strategy drawdown limit (pause)** | Pause if peak-to-trough DD **> 12%** | Worst observed OOS DD = **7.53%**; pause at ~**1.6×** observed to cap tail risk in paper. |
| **Daily loss limit** | **$210** (3% of $7k) | Session loss cap for abnormal downside days. |

---

## Strategy 006 — Futures Intraday VWAP (CONDITIONALLY APPROVED FOR PAPER TRADING)

**Condition:** OOS Sharpe is **N/A** due to insufficient intraday history. Run **60 trading days** of live paper data and re-evaluate (Sharpe, drawdown, slippage, and stability).

| Limit | Value | Rationale |
|-------|-------|-----------|
| **Max position size** | **1 @ES + 1 @NQ** simultaneously | Required cap for initial paper phase; limits exposure while collecting paper data. |
| **Intraday loss limit** | **$1,000 per instrument** | Per-instrument circuit breaker to prevent runaway intraday loss. |
| **Daily loss limit** | **$2,500** (5% of $50k) | Account-level hard stop for new entries on futures account. |
| **Strategy drawdown limit (pause)** | Pause if peak-to-trough DD **> 20%** | Sleeve-level circuit breaker while paper statistics accumulate. |
| **HARD CLOSE** | Flat **no later than 15:55 ET** daily | No overnight futures risk; mandatory operational control. |

---

## Approvals

| Strategy | Status | Notes |
|----------|--------|------|
| **002** | **APPROVED FOR PAPER TRADING** | Risk limits above. |
| **004** | **APPROVED FOR PAPER TRADING** | Risk limits above. |
| **006** | **CONDITIONALLY APPROVED (PAPER)** | Re-evaluate after **60 trading days** paper. |
| **003** | **DEFERRED** | Intraday data not yet available. |
| **005** | **DEFERRED** | Intraday options data not yet available. |

Signed: **Risk Manager — 2026-04-16**


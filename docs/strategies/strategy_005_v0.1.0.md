---
id: strategy_005
name: Options Intraday Directional
version: 0.1.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.strategy_005
asset_class: options
status: paper
---

# Strategy 005 — Options Intraday (Directional, ATM / Near-Delta)

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_005_options_intraday_directional` |
| **Semantic version** | `0.1.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | `us_options` |
| **Specification status** | Draft — ready for backtesting handoff |
| **Last updated** | `2026-04-12` |

---

## 1. Strategy identity

### 1.1 Name and purpose

**Name:** Options Intraday — Directional Breakout + RSI

**Purpose:** **Intraday** **long-call** and **long-put** trades driven by **underlying** **5-minute** price breaks vs a **rolling 30-minute** range, with **RSI(14)** confirmation on the same timeframe. Contracts are **ATM** (or nearest), **delta** targeted **0.45–0.55**, **0DTE** for **SPX** and **next available expiry** for **equities**. **Defined premium risk** per trade and **hard flatten** before RTH close.

### 1.2 Versioning and ownership

- **Version:** `0.1.0`
- **Owner:** `platform` — options chain selection and greeks via **adapter/data layer**; **no** direct broker SDK in strategy logic.
- **Tenant:** `director`.

### 1.3 Hard close

- **All option positions closed by 15:45 ET** — **no** overnight options in v0.1.0.

---

## 2. Universe (underlyings)

### 2.1 Symbols

| Type | Symbols |
|------|---------|
| **Equities / ADR** | IREN, CLS, MU, APP, AMD, GEV, TSM, PLTR, LITE, COHR, SNDK, STX, LLY |
| **Index** | **SPX** (index options — **SPX** / **SPXW** per Cboe; **cash-settled** — confirm chain root with Data Engineer) |

**Note:** **SPX** is an **index**, not a stock; data feed provides **index level** or **proxy** for “underlying” 5-minute bars.

---

## 3. Data and options selection

### 3.1 Underlying bars

- **5-minute** OHLCV on **each** underlying, **ET**, **RTH** session aligned with §4.

### 3.2 Expiry selection

| Underlying | Expiry rule (v0.1.0) |
|------------|----------------------|
| **SPX** | **0DTE** (same **calendar** session expiry — **SPXW** 0DTE where listed) |
| **All others** | **Next available listed expiry** **after** session date (**not** same-day unless 0DTE exists — **default:** **nearest** expiry **≥ T+1** calendar or next **weekly** — **document** vendor calendar) |

### 3.3 Strike and delta

- **Strike:** **At-the-money (ATM)** = strike **nearest** underlying **price** at signal time (use **last** or **mid** per product rule).
- **Call/Put side:** Per signal (§5).
- **Delta target:** Select listed series with **absolute delta** in **\[0.45, 0.55\]** **per broker greeks** at entry; if **no** contract in band, **skip** trade and **log** **`DELTA_SKIP`**.

### 3.4 Premium budget

- **Entry premium** (debit paid) **≤ $500** **per** trade.
- If **cheapest** qualifying contract **> $500**, **skip** and **log** **`PREMIUM_CAP`**.

---

## 4. Session and time gates (ET)

- **Session:** **09:30** – **16:00** RTH for underlying data; **no new entries after 15:30** (**2:30 PM**).
- **Hard exit:** **15:45** — **close all** option positions (market or limit per ops).
- **Bar convention:** Same as Strategy 003/006 — **5-minute** bars, **America/New_York**.

---

## 5. Signal definitions (underlying, 5-minute)

Let **t** index **5-minute** bars. **RSI14_t** = **Wilder RSI(14)** on **underlying closes** (continuous series across sessions **recommended** for stability).

### 5.1 Prior 30-minute range

**30 minutes** = **six** consecutive **5-minute** bars. **Prior** window **excluding** current bar **t**:

\[
H^{\text{prior30}}_t = \max_{k=1}^{6} High_{t-k}, \qquad
L^{\text{prior30}}_t = \min_{k=1}^{6} Low_{t-k}
\]

Require **t ≥ 7** within session (or cross-session — **default:** **at least 6** prior bars available).

### 5.2 BUY CALL (long call)

**Conditions** at bar **t**:

1. **Breakout:** Underlying **close** breaks above prior 30-minute **high**:

\[
\text{Close}_t > H^{\text{prior30}}_t
\]

(use **strict** inequality; optional: **Close_{t−1} ≤ H^{prior30}_{t−1}** for **fresh** cross — **default:** **Close_t > H^{prior30}_t** only).

2. **Momentum:**

\[
\text{RSI14}_t > 60
\]

3. **Time:** Bar end **≤ 15:30 ET** (no new entries after 2:30 PM).

4. **Capacity:** **< 3** total open option positions (§6); **no** duplicate underlying (§6).

### 5.3 BUY PUT (long put)

1. **Breakdown:**

\[
\text{Close}_t < L^{\text{prior30}}_t
\]

2. **Momentum:**

\[
\text{RSI14}_t < 40
\]

3. **Time** and **capacity** as above.

---

## 6. Position sizing and limits

### 6.1 Per-trade premium cap

- **Maximum debit:** **$500** **per** opening trade (defined risk **at entry** = premium paid for long options).

### 6.2 Portfolio caps

- **Maximum 3** **concurrent** option positions (**any** underlyings).
- **Total premium deployed** (sum of entry premiums of **open** positions): **≤ $1,500**.

### 6.3 One position per underlying

- **Maximum 1** open option position **per** underlying symbol at a time (one **call** **or** one **put**).

---

## 7. Exit rules (intrinsic risk management)

Let **Π₀** = **premium paid** (debit) at entry; **Π_t** = **mark** or **exit** premium (model in backtest).

### 7.1 Stop (50% of premium)

**Exit** when **option value** has **lost 50%** of premium paid:

\[
\Pi_t \le 0.5\, \Pi_0
\]

(Use **mid** or **last** — **document**; live: **stop order** or **alert**).

### 7.2 Target (100% gain on premium)

**Exit** when:

\[
\Pi_t \ge 2\, \Pi_0
\]

(**+100%** return on premium — **2×** money at risk vs **0.5×** stop → **2:1** **gain-to-loss** ratio on **premium**).

### 7.3 Hard time close

- **15:45 ET:** **Close** all positions regardless of P&L.

### 7.4 Priority

**Stop** and **target** monitored **intraday**; **15:45** **flat** overrides.

---

## 8. Regime conditions

- **No** **VIX** gate in v0.1.0.
- **Low liquidity / wide spreads:** If **bid–ask** spread exceeds **platform threshold**, **skip** entry — **parameter** for execution layer.

---

## 9. Risk profile

### 9.1 Expected Sharpe

- **Indicative:** Short-dated **directional** options are **extremely** path- and vol-dependent; **Sharpe** can be **negative** in many samples — **no** target range stated.

### 9.2 Expected max drawdown

- **Defined** by **premium** caps (**$500** / trade, **$1,500** total) but **gap** and **fill** risk can **exceed** model — stress-test.

### 9.3 Known failure modes

| Mode | Comment |
|------|--------|
| **IV crush** | Post-breakout vol drop |
| **0DTE gamma** | SPX rapid decay |
| **Spread costs** | Eat small targets |
| **Delta selection** | Greeks stale vs fast market |
| **SPX vs SPXW** | Product-specific session rules |

---

## 10. Backtesting data requirements

| Item | Requirement |
|------|-------------|
| **Underlying** | **5-minute** OHLCV, **≥ 2–3 years** |
| **Options** | **Minute** or **tick** marks for **Π_t**; **chain** history for **ATM** and **delta** |
| **SPX 0DTE** | **Special** settlement — vendor methodology |
| **Costs** | **Bid–ask** half-spread + commission **per contract** |

---

## 11. Handoff checklist

- [ ] Owner **`platform`**, tenant **`director`**, status **`paper`**
- [ ] **Universe** listed; **SPX** = **0DTE**; others **next expiry**
- [ ] **ATM**, **delta 0.45–0.55**; **premium ≤ $500**; **≤3** positions; **≤$1,500** total premium
- [ ] **Call:** **Close > prior 30m high** & **RSI > 60**; **Put:** **Close < prior 30m low** & **RSI < 40**
- [ ] **No entries after 15:30 ET**; **flat 15:45 ET**
- [ ] **Stop −50%** premium; **target +100%** premium

---

*End of specification — Strategy 005 v0.1.0*

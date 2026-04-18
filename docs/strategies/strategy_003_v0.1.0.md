---
id: strategy_003
name: Equity Intraday ORB
version: 0.1.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.strategy_003
asset_class: equity
status: paper
---

# Strategy 003 — Equity Intraday (Opening Range Breakout)

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_003_equity_intraday_orb` |
| **Semantic version** | `0.1.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | `us_equities` |
| **Specification status** | Draft — ready for backtesting handoff |
| **Last updated** | `2026-04-16` |

---

## 1. Strategy identity

### 1.1 Name and purpose

**Name:** Equity Intraday — Opening Range Breakout (ORB)

**Purpose:** Intraday **long and short** trades on a fixed symbol list using the **first 30 minutes** of RTH to define an **opening range (OR)**; enter on **volume-confirmed** breaks of OR **high** or **low**, with **stops** at the opposite OR extreme and **fixed fractional risk** per trade. **Flat by 3:55 PM ET**. **PDT (Pattern Day Trader) limits apply only when the trading account is below the $25,000 equity threshold** — see §7.

### 1.2 Versioning and ownership

- **Version:** `0.1.0`
- **Owner:** `platform` — execution via **`BrokerAdapter`** only; strategy code must not reference broker vendors.
- **Tenant:** `director` — all orders and state scoped to `tenant_id = director`.

### 1.3 Deployment

- **Paper** first; **margin account** assumptions may apply for shorts — confirm with broker.

---

## 2. Universe and session

### 2.1 Symbols (fixed)

| Symbol |
|--------|
| MU, AMD, RKLB, ASTS, APP, LRCX, CLS, CCJ, PLTR |

No substitutions in v0.1.0 without version bump.

### 2.2 Bar frequency and session (ET)

- **Bars:** **5-minute** OHLCV, **America/New_York**.
- **Operating window:** **09:30** – **15:55** inclusive (see §2.3 for bar labeling).
- **Hard flat:** **All stock positions closed by 15:55 ET** — **no overnight** equity for this strategy.

### 2.3 Opening range window

- **Opening range (OR)** = **09:30 – 10:00 ET** using **six** consecutive **5-minute** bars:
  - 09:30–09:35, 09:35–09:40, 09:40–09:45, 09:45–09:50, 09:50–09:55, 09:55–10:00.

Let \(H^{OR}\), \(L^{OR}\) be the **maximum high** and **minimum low** over those six bars **inclusive**, for symbol **i** on session date **D**:

\[
H^{OR}_{i,D} = \max_{b \in \text{OR}} High_{i,b}, \qquad
L^{OR}_{i,D} = \min_{b \in \text{OR}} Low_{i,b}
\]

**OR width:** \(W_{i,D} = H^{OR}_{i,D} - L^{OR}_{i,D}\). If \(W_{i,D} \le 0\) or missing bars, **no trades** that day for symbol **i**.

---

## 3. Volume filter (exact)

For any **candidate entry bar** **t** (5-minute bar index within the session, **after** 10:00 ET):

Let \(V_t\) be **volume** of bar **t**. Let \(\bar{V}_{t}\) be the **20-bar simple moving average** of volume over **completed** 5-minute bars **ending at t−1** (same session and prior sessions per implementation choice — **default v0.1.0:** **rolling 20 bars** on the **5-minute** series, **including** prior sessions for stability):

\[
\bar{V}_t = \frac{1}{20}\sum_{k=1}^{20} V_{t-k}
\]

**Volume surge condition:**

\[
V_t > 2 \times \bar{V}_t
\]

If **insufficient history** for 20 bars, **skip** entry (fail closed).

---

## 4. Signal definitions

Bars **after** 10:00 ET only for OR breaks. Let **Close_t**, **High_t**, **Low_t** denote bar **t** values.

### 4.1 Long (BUY) breakout

**Breakout condition** (upward):

\[
\text{Close}_t > H^{OR}_{i,D}
\]

Use **close** of bar **t** as the breakout trigger (alternative: **High_t > H^{OR}** with **Close_t** confirmation — **default:** **Close_t > H^{OR}**).

**Long signal** at **t** iff:

1. \( \text{Close}_t > H^{OR}_{i,D} \)
2. \( V_t > 2 \bar{V}_t \)
3. Time **≤ 14:00 ET** (no new entries after 2:00 PM — §6.2)
4. No existing position in **i** (§5)
5. **PDT gate** (§7): if enforcement is **on** for this account, **`IntradayPositionManager.can_day_trade()`** must allow the entry; if enforcement is **off** (equity **≥ $25,000**), **do not** block entries for PDT

### 4.2 Short (SHORT) breakdown

**Breakdown condition:**

\[
\text{Close}_t < L^{OR}_{i,D}
\]

**Short signal** at **t** iff:

1. \( \text{Close}_t < L^{OR}_{i,D} \)
2. \( V_t > 2 \bar{V}_t \)
3. Time **≤ 14:00 ET**
4. No existing position in **i**
5. **PDT gate** (§7): if enforcement is **on** for this account, **`IntradayPositionManager.can_day_trade()`** must allow the entry; if enforcement is **off** (equity **≥ $25,000**), **do not** block entries for PDT

### 4.3 One position per symbol

- **Maximum 1** open position (long **or** short) per **symbol** at a time — **no** pyramiding.

---

## 5. Position sizing and stops

### 5.1 Intraday capital and risk budget

- **Intraday capital** \(C_{\text{intraday}}\): **configurable per account** (risk approval / PM). Baseline in this document: **$12,500**; e.g. **SIM3236523M** may use **$20,000** with **$200** per-trade risk (**1%**).
- **Risk per trade:** **1%** of \(C_{\text{intraday}}\) **maximum** risk **per** new entry.

\[
R_{\text{dollar}} = 0.01 \times C_{\text{intraday}}
\]

### 5.2 Stop prices (structural)

- **Long:** stop at **opening range low** (session invalidation):

\[
S_{\text{stop}}^{\text{long}} = L^{OR}_{i,D}
\]

- **Short:** stop at **opening range high**:

\[
S_{\text{stop}}^{\text{short}} = H^{OR}_{i,D}
\]

### 5.3 Entry price

- **P_entry** = **fill price** (backtest default: **Close_t** of signal bar or **Open_{t+1}** — **document**; live: actual market fill).

### 5.4 Share count from risk

**Long** (per-share risk = \(P_{\text{entry}} - S_{\text{stop}}^{\text{long}}\)):

\[
\text{shares} = \left\lfloor \frac{R_{\text{dollar}}}{\max\left(\epsilon,\ P_{\text{entry}} - L^{OR}_{i,D}\right)} \right\rfloor
\]

**Short** (per-share risk = \(S_{\text{stop}}^{\text{short}} - P_{\text{entry}}\)):

\[
\text{shares} = \left\lfloor \frac{R_{\text{dollar}}}{\max\left(\epsilon,\ H^{OR}_{i,D} - P_{\text{entry}}\right)} \right\rfloor
\]

Use small **ε** (e.g. **$0.01**) to avoid divide-by-zero. If **risk per share** ≤ 0 or **shares < 1**, **skip** trade and **log**.

---

## 6. Entry and exit timing

### 6.1 Entry

- **Order:** **Market** (or **limit** at discretion — v0.1.0 default **market** after signal bar).
- **No new entries after 14:00 ET** (2:00 PM). Compare **bar end timestamp** to **14:00 ET**; if **strict**, bar ending **14:00** is **disallowed** for **new** entries.

### 6.2 Exit (flat by session end)

- **Stop:** Hit **L^{OR}** (long) or **H^{OR}** (short) intraday — **exit** at stop price (or next tick).
- **Time:** **Liquidate** by **15:55 ET** regardless of P&L.
- **Optional:** Trailing / target not in v0.1.0 base spec.

---

## 7. PDT constraint (Pattern Day Trader)

### 7.1 When PDT enforcement applies

- **If** the **account end-of-day equity** (or broker-reported **PDT flag** / **day-trading buying power** context) is **below $25,000**, **then** FINRA **pattern day trader** round-trip limits **may** constrain day trades — enforce via **`IntradayPositionManager.can_day_trade()`** (or equivalent) **before each entry**.
- **If** account equity is **≥ $25,000** (PDT rule **does not** restrict day trading in the usual way for a **margin** account with sufficient equity), **do not** block entries using PDT / **three round-trips in five days** / **`PDT_LIMIT`** for this strategy on that account.

### 7.2 Platform gate (conditional)

When **§7.1** says enforcement is **on** for the bound account:

1. Call **`IntradayPositionManager.can_day_trade()`** (scoped to **`tenant_id`** and **account**).
2. If **`false`**: **skip** the trade, **log** **`PDT_LIMIT`** (or manager-provided code).
3. If **`true`**: submit via **`BrokerAdapter`**.

When enforcement is **off**, **skip** the **`can_day_trade()`** PDT check (optional: still **log** day-trade counts for **telemetry** only).

**Note:** Sub-$25k accounts must still track round-trips per **account** and **rolling window** per regulatory and product rules.

---

## 8. Regime conditions

- **No** separate **VIX** filter in v0.1.0 unless added later.
- **Halt / circuit breaker:** If symbol halted, **no** new entries; manage open risk per ops.

---

## 9. Risk profile

### 9.1 Expected Sharpe

- **Indicative:** ORB on single names is **highly variable**; **ex ante** annualized Sharpe **−0.2 to +0.8** net of realistic costs — **not** a forecast.

### 9.2 Expected max drawdown

- **Gap** through OR stop, **slippage**, and **sequence** of full per-trade risk (**1%** of \(C_{\text{intraday}}\)) losses can produce **>10–25%** drawdowns on small sleeves if not capped — consider **daily max loss** in future versions.

### 9.3 Known failure modes

| Mode | Comment |
|------|--------|
| **False breakouts** | Price reverts through OR |
| **OR too narrow** | Tiny \(W\) → huge share count from \$125 risk |
| **Volume spikes** | News without follow-through |
| **PDT skips** | (Sub-$25k accounts) missed entries when round-trip limit hit |

---

## 10. Backtesting data requirements

| Item | Requirement |
|------|-------------|
| **Bars** | **5-minute** OHLCV, **≥ 2–3 years** per symbol |
| **Calendar** | NYSE sessions, half-days |
| **Costs** | Per-share commission + **slippage** (especially at open) |
| **Shortability** | Locate / borrow assumptions for shorts |
| **PDT sim** | For **sub-$25k** accounts, model **`can_day_trade()`**; for **≥$25k**, run **unconstrained** PDT sensitivity as optional |

---

## 11. Handoff checklist

- [ ] Owner **`platform`**, tenant **`director`**, status **`paper`**
- [ ] OR: **9:30–10:00** ET; **H^{OR}, L^{OR}**; breakout **Close** vs OR + **V > 2×SMA(V,20)**
- [ ] No entries after **14:00 ET**; flat **15:55 ET**
- [ ] Risk **1%** of \(C_{\text{intraday}}\) (e.g. **$125** @ **$12.5k**, **$200** @ **$20k**); **shares = R / |entry − stop|**
- [ ] **PDT:** **`can_day_trade()`** only when account **&lt; $25k** equity; **no** PDT block when **≥ $25k**

---

*End of specification — Strategy 003 v0.1.0*

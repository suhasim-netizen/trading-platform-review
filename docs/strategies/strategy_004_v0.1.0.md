---
id: strategy_004
name: Equity Swing Pullback
version: 0.1.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.swing_pullback
asset_class: equity
status: paper
---

# Strategy 004 — Equity Swing (Pullback in Uptrend)

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_004_equity_swing_pullback` |
| **Semantic version** | `0.1.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | `us_equities` |
| **Specification status** | Draft — ready for backtesting handoff |
| **Last updated** | `2026-04-12` |

---

## 1. Strategy identity

### 1.1 Name and purpose

**Name:** Equity Swing — Pullback to 10-Day SMA in Uptrend

**Purpose:** **Multi-day** long-only trades on a fixed **tech / industrial** symbol list: require **price above the 50-day SMA** (trend), a **pullback** toward the **10-day SMA** within a **1%** band, then a **close back above** the 10-day SMA with **elevated volume**. Exits use a **fixed take-profit**, **fixed stop**, and **maximum 10 trading days** in position.

### 1.2 Versioning and ownership

- **Version:** `0.1.0`
- **Owner:** `platform` — per ADR 0003; orders via **`BrokerAdapter`** only.
- **Tenant:** `director`.

### 1.3 Hold period

- **Minimum:** **2** trading days (no exit **before** day 2 except stop — **clarification:** stop may exit on day 1; **time stop** at **10** days **from entry session**).
- **Maximum:** **10** trading days — **mandatory** exit on **close** of the **10th** trading day after entry unless already exited.

**Default v0.1.0:** **Time stop** = exit at **close** of **day 10** counting **entry day as day 1** (or **entry+9** sessions — **document** in implementation; pick **one** convention and keep constant).

---

## 2. Universe and data

### 2.1 Symbols (fixed)

| Symbol |
|--------|
| LASR, LITE, COHR, SNDK, STRL |

### 2.2 Bar frequency

- **Daily** OHLCV, **official RTH close** (or adjusted close per Data Engineer).
- **Splits:** **Split-adjusted** prices for SMAs and returns.

### 2.3 Warmup

- Require **≥ 50** trading days of history before first signal (**50-day SMA**).

---

## 3. Indicator definitions (exact)

Let **C_t**, **L_t**, **V_t** be close, low, volume on **trading day** **t** (ascending).

### 3.1 Moving averages

**50-day SMA:**

\[
\text{SMA50}_t = \frac{1}{50}\sum_{k=0}^{49} C_{t-k}
\]

**10-day SMA:**

\[
\text{SMA10}_t = \frac{1}{10}\sum_{k=0}^{9} C_{t-k}
\]

### 3.2 Volume average

**20-day average volume:**

\[
\bar{V}_{20,t} = \frac{1}{20}\sum_{k=0}^{19} V_{t-k}
\]

---

## 4. Signal — pullback and entry

### 4.1 Uptrend filter (must hold on entry day **t**)

\[
C_t > \text{SMA50}_t
\]

### 4.2 Pullback to 10-day SMA (within 1%)

**Pullback day** **p** (with **p < t**): price **interacts** with the 10-day SMA **within 1%** tolerance. **Definition v0.1.0:**

\[
\frac{\left|L_p - \text{SMA10}_p\right|}{\text{SMA10}_p} \le 0.01
\]

**and** the session shows **pullback character** from above:

\[
L_p \le \text{SMA10}_p \quad \text{(low at or below SMA10)}
\]

**Alternative** (if **p** same as **t**): allow **single-bar** pullback — **default sequence:** require **p = t−1** **or** **p = t−2** with **entry on t** (tune in backtest). **Minimal spec:** there exists **at least one** day **p** in **{t−1, t−2}** satisfying the **band** and **L_p ≤ SMA10_p**.

### 4.3 Reclaim (entry trigger on day **t**)

\[
C_t > \text{SMA10}_t
\]

### 4.4 Volume on entry day

\[
V_t > 1.2 \times \bar{V}_{20,t}
\]

### 4.5 Combined BUY (entry at **t** close or **t+1** open)

**Long entry** when **all** hold:

1. \( C_t > \text{SMA50}_t \)
2. Pullback condition §4.2 for some **p** in lookback (default **p ∈ {t−1, t−2}**)
3. \( C_t > \text{SMA10}_t \)
4. \( V_t > 1.2 \bar{V}_{20,t} \)
5. **Max positions** not exceeded (§5)

**Execution default:** **Market** next session **open** (**t+1**) after signal on **t** (or **close t** — **document**).

---

## 5. Position sizing

- **Total capital** (baseline): **$12,500**.
- **Maximum 2** concurrent positions.
- **Per position cap:** **$6,250** notional (approximate **shares × price** at entry).

\[
\text{shares}_i = \left\lfloor \frac{6250}{P_{\text{entry}}} \right\rfloor
\]

- **Equal risk intent:** two slots of **50%** capital each when both filled.

---

## 6. Exit conditions (first trigger wins)

Let **P₀** = entry fill price.

### 6.1 Take-profit (+8%)

\[
P_{\text{TP}} = P_0 \times 1.08
\]

**Exit** when **close** or **intraday high** ≥ **P_TP** (implementation: **high** crosses threshold — **document**).

### 6.2 Stop-loss (−4%)

\[
S_{\text{stop}} = P_0 \times (1 - 0.04) = P_0 \times 0.96
\]

**Exit** when **low** ≤ **S_stop** (gap-aware fill model in backtest).

**Reward:risk:** **8% / 4% = 2 : 1** (meets **minimum 2:1**).

### 6.3 Time stop (10 trading days)

- **Exit** no later than **close** of the **10th** trading day **after** entry (choose **inclusive** counting — **default:** entry day = **day 1**, exit **EOD day 10**).

### 6.4 Priority

1. **Intraday** stop if path monitored; else **EOD** logic.  
2. **TP** vs **time** — first event wins.

---

## 7. Regime conditions

- **Optional future:** **VIX** filter — **off** in v0.1.0.
- **Earnings:** **No** mandatory avoidance in v0.1.0 — **flag** as risk.

---

## 8. Risk profile

### 8.1 Expected Sharpe

- **Indicative:** Swing pullback systems on **small baskets** often show **0.3–0.9** **gross** in favourable samples; **net** lower — **wide** uncertainty.

### 8.2 Expected max drawdown

- **15%–35%** plausible on **concentrated** equity swings without portfolio diversification.

### 8.3 Known failure modes

| Mode | Comment |
|------|--------|
| **Trend breaks** | **50-day** filter lags |
| **Whipsaw** | Multiple false pullbacks |
| **Gap risk** | Stop worse than 4% |
| **Volume spikes** | One-day noise |

---

## 9. Backtesting data requirements

| Item | Requirement |
|------|-------------|
| **History** | **≥ 3 years** daily OHLCV per symbol |
| **Costs** | Commission + slippage |
| **Pullback lookback** | Sensitivity on **p ∈ {t−1}** vs **{t−1,t−2,t−3}** |

---

## 10. Handoff checklist

- [ ] Owner **`platform`**, tenant **`director`**, status **`paper`**
- [ ] **Uptrend:** **C > SMA50**; **pullback** within **1%** of **SMA10** with **L ≤ SMA10**; **reclaim** **C > SMA10**; **V > 1.2× avg(V,20)**
- [ ] **TP +8%**, **stop −4%**, **time 10** sessions
- [ ] **Max 2** positions, **$6,250** each on **$12.5k**

---

*End of specification — Strategy 004 v0.1.0*

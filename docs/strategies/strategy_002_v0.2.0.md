---
id: strategy_002
name: Equity Momentum Intraday
version: 0.2.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.momentum
asset_class: equity
status: paper
bar_interval: 5m
eod_close: true
---

# Strategy 002 — Equity Momentum Intraday

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_002_equity_momentum_intraday` |
| **Semantic version** | `0.2.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | US equities (intraday, long-only) |
| **Last updated** | 2026-04-12 |

---

## 1. Director profile (capital and PDT)

| Item | Value |
|------|--------|
| **Equity account** | **$50,000** minimum equity |
| **PDT status** | **Confirmed** — **no** round-trip count limit for this deployment |
| **Intraday buying power** | **4×** → **$200,000** notional capacity (regulatory / broker — verify live) |
| **Futures** | **Separate** **$50k** account (not used by this strategy) |

This specification assumes **PDT buying power** is available; **do not** apply Strategy 003–style `can_day_trade()` caps to this strategy.

---

## 2. Strategy identity

### 2.1 Name and purpose

**Name:** Equity Momentum Intraday

**Purpose:** **Same-day** **long-only** momentum breakouts on a **fixed four-name** universe using **5-minute** bars, **session VWAP** trend filter, **RSI(14)** confirmation, and **volume surge**. **All positions closed by 15:55 ET** — **no overnight** stock.

### 2.2 Type

- **INTRADAY ONLY** — every position **opened and closed** on the **same** US equity session.
- **Direction:** **LONG only** (no shorting in v0.2.0).

### 2.3 Universe (fixed)

| Symbol |
|--------|
| **AVGO**, **LLY**, **TSM**, **GEV** |

---

## 3. Session, bars, and VWAP

### 3.1 Bar interval and session (ET)

- **Bars:** **5-minute** OHLCV, **America/New_York**.
- **Trading window:** **09:35** – **15:55** inclusive (first signal bar **9:35–9:40**, last **15:50–15:55** per vendor bar labelling — **fix one** convention in implementation).
- **Hard EOD close:** **15:55 ET** — **market order** (or MOC-equivalent) to **fully close** all positions — **no exceptions**, regardless of P&L.

### 3.2 Session VWAP (trend filter)

**Session anchor:** First 5-minute bar of the strategy window (**09:35–09:40 ET**).  
Typical price: \(\text{TP}_k = (H_k+L_k+C_k)/3\).

**VWAP** at bar **t** (cumulative from session start through **t**):

\[
\text{VWAP}_t = \frac{\sum_{k=1}^{t} \text{TP}_k \cdot V_k}{\sum_{k=1}^{t} V_k}
\]

If cumulative volume is zero, **no trade**.

**Trend filter (long):** **Close_t > VWAP_t** (evaluated on **signal bar** **t**).

---

## 4. Signal — momentum breakout (exact)

Index **t** = current **5-minute** bar. **t−1** = **previous** bar (same session; **no** cross-session **t−1** for first bar after open — **skip** signal if **t−1** missing).

### 4.1 Volume average

**20-bar** simple mean of volume over bars **t−20** through **t−1** (require **20** prior bars in session **or** allow prior session — **default v0.2.0:** **rolling 20** five-minute bars **including** prior sessions for stability):

\[
\bar{V}_t = \frac{1}{20}\sum_{k=1}^{20} V_{t-k}
\]

### 4.2 RSI

**RSI(14)** on **5-minute** **closes** (Wilder smoothing). **Continuous** series across sessions recommended.

### 4.3 LONG entry — all must be true

1. **Breakout:** Price **breaks above** the **high** of the **previous** 5-minute bar:

\[
\text{Close}_t > \text{High}_{t-1}
\]

2. **Volume surge:**

\[
V_t > 1.5 \times \bar{V}_t
\]

3. **VWAP filter:** \(\text{Close}_t > \text{VWAP}_t\).

4. **Momentum:** \(\text{RSI14}_t > 55\).

5. **Time:** Bar **end timestamp** in **\[09:35, 14:00\]** ET — **no new entries** after **14:00 ET** (exclusive of new entries on bar ending **after** 14:00; **document** boundary).

6. **Flat per symbol:** **No** existing position in **this** symbol.

### 4.4 Entry execution

- **Market order** **immediately** on **signal bar close** (backtest: **Close_t** + slippage; live: market on close of bar).

---

## 5. Exits (first trigger wins)

Let **P₀** = entry fill price; **H^{close}_{\max}** = highest **close** achieved **since entry** while position open.

### 5.1 Stop loss (−1.5%)

\[
S_{\text{stop}} = P_0 \times (1 - 0.015)
\]

**Exit** if **intraday low** hits **≤ S_stop** (fill model: stop price or worse).

### 5.2 Profit target (+3%)

\[
P_{\text{TP}} = P_0 \times 1.03
\]

**Reward : risk** = **3% : 1.5%** = **2 : 1** (minimum met).

### 5.3 Trailing stop (after +2% unrealized on closes)

**Arm** trailing when **highest close since entry** first reaches **≥ P₀ × 1.02**.

Once armed, **trail stop** = **1%** below **running highest close**:

\[
S_{\text{trail}} = H^{\text{close}}_{\max} \times (1 - 0.01)
\]

**Exit** when **Close** or **Low** breaches **S_trail** (implementation: typically **close** below **S_trail** or **low** ≤ **S_trail** — **document**).

**Priority vs fixed stop:** **Whichever is higher** (tighter for long) between **S_stop** and **S_trail** once trailing is active.

### 5.4 Hard close

- **15:55 ET** — **close entire position** (market); overrides other rules.

---

## 6. Position sizing (PDT 4× context)

| Parameter | Value |
|-------------|--------|
| **Equity base** | **$50,000** |
| **Risk per trade** | **1%** of equity = **$500** **at risk** vs **structural** stop |
| **Stop distance** | **1.5%** of **entry price** (price risk, not gap-proof) |

**Share count:**

\[
\text{shares} = \left\lfloor \frac{500}{P_0 \times 0.015} \right\rfloor = \left\lfloor \frac{500}{0.015\, P_0} \right\rfloor
\]

| Constraint | Value |
|------------|--------|
| **Max position value** (notional) | **$25,000** per symbol (**half** of **$50k** intraday buying-power **cap** narrative — enforce in risk engine) |
| **Max concurrent positions** | **2** (across symbols) |

If **shares × P₀** would exceed **$25,000**, **cap** shares so notional ≤ **$25k** and **log** **`NOTIONAL_CAP`**.

---

## 7. Risk controls

### 7.1 Daily loss limit (equity sleeve)

- **$1,500** maximum **realized + mark-to-market** loss **for this strategy** in a session (**3%** of **$50k**).
- If **hit** → **no new entries** for **rest of session**; **manage** open positions per §5.

### 7.2 VIX circuit breaker (new entries only)

- **No new entries** if **VIX > 30** (use **prior** session **close** or **same-day** open per product rule — **default:** **most recent available VIX close** before signal bar).
- **Open positions:** **not** forced flat solely by VIX in v0.2.0 (optional future).

---

## 8. Regime and data

- **VIX:** Daily series for circuit breaker.
- **Bars:** **5m** OHLCV **≥ 2 years** per symbol preferred.

---

## 9. Risk profile (indicative)

- **Sharpe:** Highly variable for intraday equity; **wide** ex ante range; **validate** OOS.
- **Max DD:** **Single-name** and **concentrated** — **large** tail; **daily loss cap** limits **runaway** days.

---

## 10. Backtesting requirements

- **5-minute** history; **session** VWAP from **09:35** anchor.
- **Costs:** Commission + **slippage** on market entries/exits.
- **No** overnight positions in sim — **force flat** **15:55**.

---

## 11. Handoff checklist

- [ ] **version** `0.2.0`; **bar_interval** `5m`; **eod_close** `true`
- [ ] Long-only; **Close > High_{t−1}**; **V > 1.5×avg(V,20)**; **Close > VWAP**; **RSI > 55**; **time ≤ 14:00** entry cutoff
- [ ] Stop **1.5%**; target **3%**; trail after **+2%** closes, **1%** off **high close**
- [ ] **$500** risk / **1.5%** stop; **≤$25k**/symbol; **2** positions max
- [ ] **Daily loss $1,500**; **VIX > 30** block new entries

---

*End of specification — Strategy 002 v0.2.0*

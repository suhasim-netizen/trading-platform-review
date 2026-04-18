---
id: strategy_006
name: Futures Intraday VWAP Momentum
version: 0.2.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.futures_intraday
asset_class: futures
status: paper
bar_interval: 1m
eod_close: true
---

# Strategy 006 — Futures Intraday VWAP Momentum

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_006_futures_intraday_vwap_momentum` |
| **Semantic version** | `0.2.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | US index futures |
| **Last updated** | 2026-04-12 |

---

## 1. Director profile (futures account)

| Item | Value |
|------|--------|
| **Futures account** | **$50,000** (separate from equity) |
| **This strategy** | Uses **futures** sleeve only |

---

## 2. Strategy identity

### 2.1 Name and purpose

**Name:** Futures Intraday VWAP Momentum

**Purpose:** **Intraday** **long** and **short** trades on **CME E-mini S&P 500** and **E-mini Nasdaq-100** using **VWAP cross** detection, **RSI(14)** on **1-minute** bars, and **volume confirmation**. **Flat by 15:55 ET** — **no overnight** positions **ever**.

### 2.2 Type

- **INTRADAY ONLY** — **all** positions opened and closed **same session**.

### 2.3 Instruments

| Symbol | Contract | Point value (v0.2.0 spec) |
|--------|----------|---------------------------|
| **ES** | E-mini S&P 500 | **$50** / point |
| **NQ** | E-mini Nasdaq-100 | **$20** / point |

**Micros (MES/MNQ):** Out of scope unless Risk approves notional parity — v0.2.0 assumes **one ES** / **one NQ** **mini** contract as specified below.

---

## 3. Session, bars, and VWAP

### 3.1 Bar interval and session (ET)

- **Bars:** **1-minute** OHLCV.
- **Window:** **09:35** – **15:55** ET (signals and management; **hard flat** at **15:55**).
- **Hard EOD close:** **15:55 ET** — **market** (or MOC where available) — **100% flat** — **no exceptions**.

### 3.2 Session VWAP

**Anchor:** First **1-minute** bar of the strategy session (**09:35:00–09:35:59** ET or bar labelled **09:35** — **fix** vendor convention).

\[
\text{TP}_k = \frac{H_k+L_k+C_k}{3}, \qquad
\text{VWAP}_t = \frac{\sum_{k=1}^{t} \text{TP}_k \cdot V_k}{\sum_{k=1}^{t} V_k}
\]

---

## 4. Volume average

At bar **t**:

\[
\bar{V}_t = \frac{1}{20}\sum_{k=1}^{20} V_{t-k}
\]

(Require **20** prior bars; **default:** **rolling** 20 **1-minute** bars, **may** include prior session.)

**Surge condition:** \(V_t > 1.2 \times \bar{V}_t\).

---

## 5. RSI

**RSI(14)** on **1-minute** **closes** (Wilder), **continuous** series recommended.

---

## 6. Entry signals

**Time gate:** Signal bar **end** must satisfy **09:35 ≤ time ≤ 14:00 ET** — **no new entries** after **14:00 ET**.

**Max positions:** **One** net position **per instrument** (**ES** or **NQ**) — **no** scale-in.

### 6.1 LONG (per instrument, independent)

All must hold on bar **t**:

1. **VWAP cross from below:**

\[
\text{Close}_{t-1} \le \text{VWAP}_{t-1} \quad \land \quad \text{Close}_t > \text{VWAP}_t
\]

2. **Momentum:** \(\text{RSI14}_t > 55\).

3. **Volume:** \(V_t > 1.2 \times \bar{V}_t\).

4. **Time** and **flat** checks.

### 6.2 SHORT (per instrument, independent)

All must hold on bar **t**:

1. **VWAP cross from above:**

\[
\text{Close}_{t-1} \ge \text{VWAP}_{t-1} \quad \land \quad \text{Close}_t < \text{VWAP}_t
\]

2. **Momentum:** \(\text{RSI14}_t < 45\).

3. **Volume:** \(V_t > 1.2 \times \bar{V}_t\).

4. **Time** and **flat** checks.

### 6.3 Opposite signal — exit and reverse

If **long** and **SHORT** signal **both** fire on same bar (rare), **default:** **exit long** and **enter short** per spec **OR** **flatten only** — **v0.2.0 default:** **exit and reverse** (close **1** ES/NQ long, open **1** ES/NQ short at same bar’s process — **document** fill sequencing).

If **short** and **LONG** signal — **reverse** to long symmetrically.

---

## 7. Position sizing (fixed contract + dollar risk)

| Instrument | Contracts | Stop (points) | Risk per stop |
|------------|-----------|---------------|----------------|
| **ES** | **1** | **4** points | **4 × $50 = $200** |
| **NQ** | **1** | **10** points | **10 × $20 = $200** |

**One** contract **maximum** **per** instrument at any time.

---

## 8. Exit conditions (first trigger wins)

### 8.1 Stop loss

- **ES:** **4 points** adverse from **entry fill**.
- **NQ:** **10 points** adverse from **entry fill**.

### 8.2 Profit target (2 : 1 vs stop)

- **ES:** **+8** points (**8 × $50 = $400** vs **$200** risk).
- **NQ:** **+20** points (**20 × $20 = $400** vs **$200** risk).

### 8.3 Hard close

- **15:55 ET** — **market** flatten — **overrides** stop/target.

### 8.4 Opposite signal

- **Close** current position and **open** opposite direction per §6.3 (counts as **exit** then **new entry** — subject to **daily loss** gate for **new** entry if loss limit hit).

---

## 9. Risk controls

### 9.1 Daily loss limit (futures sleeve)

- **$2,500** max **strategy** loss per session (**5%** of **$50k** futures equity).
- If **hit** → **no new entries** for **rest of session**; **still flatten** by **15:55**.

### 9.2 Overnight

- **No** overnight positions — **ever** (restate: **mandatory** flat **15:55**).

---

## 10. Risk profile (indicative)

- **Sharpe:** **Highly** regime-dependent; validate OOS.
- **Max DD:** **Sequence** of **$200** losses can compound; **daily cap** bounds **worst day** not **worst month**.

---

## 11. Backtesting data requirements

- **1-minute** OHLCV **ES** and **NQ**, **≥ 2–3 years**.
- **Costs:** Round-turn commission + **slippage** (ticks).
- **Force flat** **15:55** every session.

---

## 12. Handoff checklist

- [ ] **version** `0.2.0`; **bar_interval** `1m`; **eod_close** `true`
- [ ] **VWAP** cross + **RSI** + **volume 1.2×**; entries **09:35–14:00**
- [ ] **ES:** stop **4** / target **8** pts; **NQ:** stop **10** / target **20** pts; **$200** risk each
- [ ] **Opposite signal** → exit & reverse
- [ ] **Daily loss $2,500**; **max 1** lot per instrument

---

*End of specification — Strategy 006 v0.2.0*

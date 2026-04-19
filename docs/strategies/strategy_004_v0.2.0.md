---
id: strategy_004
name: Equity Swing Pullback
version: 0.2.1
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.swing_pullback
asset_class: equity
status: paper
bar_interval: 1D
eod_close: false
allocated_capital_usd: 30000
instruments:
  - NVDA
  - ARM
  - AVGO
  - AMD
  - SMCI
  - GEV
  - LLY
  - MU
  - TSM
  - ORCL
  - CRM
  - ADBE
  - NOW
  - PANW
  - CRWD
  - SNOW
  - DDOG
  - HUBS
---

# Strategy 004 — Equity Swing (Pullback / Pushback) v0.2.1

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_004_equity_swing_pullback` |
| **Semantic version** | `0.2.1` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | US equities (long / short) |
| **Paper account** | **SIM3236523M** |
| **Allocated capital** | **$30,000** |
| **Specification status** | Retrofit — backtest vs v0.1.0 required |
| **Last updated** | 2026-04-12 |

---

## 0. Rationale for v0.2.0 (Quant)

**v0.1.0 baseline** (representative backtest): ~**52%** win rate, **~1.6** profit factor (per reviewer); **long-only**, **no VIX regime filter**, **fixed %** stops/targets, **10**-session max hold **truncate** trend legs.

**v0.2.0** addresses:

| Gap in v0.1.0 | v0.2.0 change |
|-----------------|----------------|
| Long-only | **Short** sleeve mirroring **pullback-to-moving-average** logic in **downtrends** |
| No regime filter | **VIX ∈ [15, 30]** — skip **complacent** and **panic** tape for **swing** holds |
| Fixed 4% / 8% exits | **ATR(14)**-scaled **stop** and **target** (**2× ATR** / **4× ATR** vs entry) |
| 10-day max hold | **20 calendar days** max in position |
| Earnings blind | **Optional** **5-day** pre-earnings **no-entry**, **no hold through** earnings |

**Strategy 003 ORB futures** path **deprecated** for production after **failed** backtests; **this** retrofit is the **approved fallback** pending **v0.2.0** validation.

---

## 1. Strategy identity

### 1.1 Name and purpose

**Name:** Equity Swing — Pullback (Long) / Pushback to Resistance (Short)

**Purpose:** **Multi-day** **long** and **short** trades on a **fixed** **eighteen**-symbol universe (see frontmatter ``instruments``). **Longs** buy **pullbacks** to **SMA10** in **uptrends**; **shorts** sell **counter-trend bounces** into **SMA10** in **downtrends** confirmed by **SMA50 < SMA200**. **VIX** gating and **ATR**-based exits adapt risk to **volatility**; **optional** **earnings** rules reduce **event** risk.

### 1.2 Versioning and ownership

- **Version:** `0.2.0`
- **Owner:** `platform` — orders via **`BrokerAdapter`** only.
- **Tenant:** `director`.

### 1.3 Hold period

- **Maximum:** **20 calendar days** from **entry date** (inclusive of entry day as **day 1** — **document** exact **calendar** vs **trading-day** interpretation in implementation; **default v0.2.0:** **20 calendar days** to match spec text).
- **Minimum:** No **minimum** hold before **exit** except **stops** / **targets** / **earnings** / **time** stop.

---

## 2. Universe, account, and data

### 2.1 Symbols (unchanged)

| Symbol |
|--------|
| **LASR**, **LITE**, **COHR**, **SNDK**, **STRL** |

### 2.2 Account and capital

| Field | Value |
|--------|--------|
| **Paper account** | **SIM3236523M** |
| **Allocated capital** | **$30,000** |
| **Max concurrent positions** | **2** |
| **Per-position notional cap** | **$3,500** (50% sleeve per slot when both filled) |

### 2.3 Bar frequency

- **Daily** OHLCV, **split-adjusted** closes for indicators and **ATR**.

### 2.4 Warmup

- Require **≥ 200** trading days before first signal (**SMA200**), plus **ATR(14)** stability.

---

## 3. Indicators (exact)

Let **C, H, L, V** be **OHLCV** on **day** **t**.

### 3.1 Moving averages

\[
\text{SMA10}_t,\ \text{SMA50}_t,\ \text{SMA200}_t
\]

— **simple** **rolling** means over **10**, **50**, **200** **closes**.

### 3.2 ATR(14) (Wilder)

**True range** \(\text{TR}_t = \max(H_t - L_t,\ |H_t - C_{t-1}|,\ |L_t - C_{t-1}|)\). **ATR(14)** = **Wilder** smoothed **ATR** over **14** periods.

### 3.3 RSI(14)

**RSI(14)** on **closes** (Wilder), used **only** for **short** **entry** **filter** (§4.3).

### 3.4 Volume

\[
\bar{V}_{20,t} = \frac{1}{20}\sum_{k=0}^{19} V_{t-k}
\]

---

## 4. VIX regime filter (CHANGE 2)

### 4.1 Rule

**New entries** (long or short) **only** if:

\[
15 \le \text{VIX}_{\text{session}} \le 30
\]

| Condition | Action |
|-----------|--------|
| **VIX < 15** | **No new entries** — **complacent** regime; **gaps** and **follow-through** often **too small** for **swing** edge |
| **VIX > 30** | **No new entries** — **too volatile** for **multi-day** **mechanical** holds |

### 4.2 Timing and cache

- **Evaluate** **VIX** **once per session** at **US equity open** (or first available **daily** **official** **print** — **09:30 ET** **benchmark**).
- **Cache** **VIX** for **the** **session** — **all** symbols **share** **the** **same** **flag** **that** **day**.

### 4.3 Missing VIX

- **Fail closed:** **no** **new** **entries**; **manage** **open** **positions** **per** **exits** **only**.

---

## 5. Long entry (retained from v0.1.0, plus filters)

### 5.1 Trend

\[
C_t > \text{SMA50}_t
\]

### 5.2 Pullback to SMA10 (within 1%) — prior day **p**

Exist **p ∈ {t−1, t−2}** such that:

\[
\frac{|L_p - \text{SMA10}_p|}{\text{SMA10}_p} \le 0.01,\quad L_p \le \text{SMA10}_p
\]

### 5.3 Reclaim

\[
C_t > \text{SMA10}_t
\]

### 5.4 Volume

\[
V_t > 1.2 \times \bar{V}_{20,t}
\]

### 5.5 Combined LONG entry

**All** must hold, **and** §4 **VIX** **OK**, **and** §8 **earnings** **allows** **entry**, **and** **capacity** **OK**:

1. §5.1–§5.4  
2. **Not** already **long** **this** **symbol**

**Execution default:** **Market** **next** **open** **after** **signal** **day** **t** (or **close** **t** — **document**).

---

## 6. Short entry (CHANGE 1 — mirror of long)

### 6.1 Downtrend

\[
C_t < \text{SMA50}_t
\]

### 6.2 Long-term downtrend confirmation

\[
\text{SMA50}_t < \text{SMA200}_t
\]

### 6.3 Pullback **up** to SMA10 (resistance zone)

**Prior day** **p ∈ {t−1, t−2}**: **counter-trend** **bounce** **into** **SMA10**:

\[
\frac{|H_p - \text{SMA10}_p|}{\text{SMA10}_p} \le 0.01,\quad H_p \ge \text{SMA10}_p
\]

(**High** **at** **or** **above** **resistance** **within** **1%** **band**.)

### 6.4 Rejection (short trigger on **t**)

\[
C_t < \text{SMA10}_t
\]

### 6.5 RSI filter (bearish momentum)

\[
\text{RSI(14)}_t < 45
\]

### 6.6 Volume

\[
V_t > 1.2 \times \bar{V}_{20,t}
\]

### 6.7 Combined SHORT entry

**All** must hold, **plus** §4 **VIX**, §8 **earnings**, **capacity**, **and** **locate**/**margin** **eligibility** **for** **short**:

1. §6.1–§6.6  
2. **Not** already **short** **this** **symbol**

---

## 7. Exits — ATR-based (CHANGE 3)

Let **P₀** = **entry** **fill**. Let **ATR** = **ATR(14)** **evaluated** **on** **entry** **day** **t** ( **same** **bar** **as** **signal** **confirmation** — **document** **if** **ATR** **uses** **t** **or** **t−1** **close**; **default:** **ATR_t** **known** **at** **entry** **decision**).

### 7.1 Long

**Stop (below entry):**

\[
S_{\text{long}} = P_0 - 2 \times \text{ATR}_t
\]

**Target (above entry):**

\[
T_{\text{long}} = P_0 + 4 \times \text{ATR}_t
\]

**Reward : risk** = **4 ATR : 2 ATR** = **2 : 1**.

### 7.2 Short

**Stop (above entry):**

\[
S_{\text{short}} = P_0 + 2 \times \text{ATR}_t
\]

**Target (below entry):**

\[
T_{\text{short}} = P_0 - 4 \times \text{ATR}_t
\]

### 7.3 Trigger priority

**First** **to** **trigger** **wins** — **daily** **close** **or** **intraday** **extremes** **per** **sim** **convention**.

### 7.4 Time stop (CHANGE 4)

- **Exit** **no** **later** **than** **close** **of** **the** **session** **that** **ends** **the** **20th** **calendar** **day** **after** **entry** **date** (**inclusive** **counting** — **implement** **with** **exchange** **calendar**).

---

## 8. Earnings filter (CHANGE 5 — optional)

| Rule | Behavior |
|------|----------|
| **E−5 to E−1** | **No** **new** **entry** **if** **earnings** **within** **5** **calendar** **days** |
| **Through earnings** | **Do** **not** **hold** **across** **earnings** **release** |
| **If** **held** | **Exit** **full** **position** **on** **close** **of** **session** **before** **earnings** **day** |

**Status:** **Optional** — **enable** **when** **earnings** **calendar** **data** **is** **available** **in** **pipeline**; **if** **unavailable**, **log** **`EARNINGS_FILTER_OFF`** **and** **run** **without** **this** **block**.

---

## 9. Risk controls

- **Max** **2** **positions** **total** (**long** **and** **short** **combined** **across** **universe**).
- **Daily** **loss** **limit** — **router** / **risk** **module** ( **not** **duplicated** **here** ).
- **No** **re-entry** **same** **symbol** **same** **direction** **after** **stop** **same** **week** — **optional** **tightening** **for** **implementation**.

---

## 10. Expected metrics (paper / backtest targets)

These are **evaluation** **targets** **after** **retrofit**, **not** **guarantees**:

| Metric | Target |
|--------|--------|
| **Win rate** | **≥ 56%** |
| **Profit factor** | **≥ 1.8** |
| **Max drawdown** | **< 12%** (on **allocated** **$30k** **sleeve** **or** **as** **reported** **by** **engine**) |

---

## 11. Backtesting data requirements

- **Daily** **OHLCV** **2022–2026** ( **minimum** **overlap** **with** **v0.1.0** **run** **for** **A/B** ).
- **VIX** **daily**.
- **Costs:** **Commission**, **short** **borrow** **where** **applicable**, **slippage**.
- **Compare** **v0.2.0** **vs** **v0.1.0** **on** **identical** **data** **and** **date** **range**.

---

## 12. Handoff — Backtesting Engineer

**Request:**

1. **Backtest** **Strategy 004** **`v0.2.0`** **per** **this** **document** ( **long** + **short** + **VIX** + **ATR** **exits** + **20**-**day** **calendar** **time** **stop**; **earnings** **filter** **off** **unless** **calendar** **wired** ).
2. **Compare** **against** **Strategy 004** **`v0.1.0`** **on** **the** **same** **dataset** **and** **window** **(2022–2026** **or** **widest** **common** **history** **available** **per** **symbol** **)**.
3. **Report** **side**-**by**-**side:** **win** **rate**, **profit** **factor**, **max** **DD**, **Sharpe**, **trade** **count**, **long** **vs** **short** **contribution**.
4. **Goal:** **Confirm** **improvement** **vs** **baseline** **(52%** **WR**, **~1.6** **PF)** **and** **validate** **§10** **targets** **before** **PM** **signoff**.

---

## 13. Handoff checklist (implementation)

- [ ] **version** `0.2.0`; **`swing_pullback`** **handler** **upgrade** **or** **parallel** **module**
- [ ] **Long** **v0.1** **logic** + **VIX** + **ATR** **exits** + **20**-**calendar**-**day** **max** **hold**
- [ ] **Short** **mirror** **with** **SMA200**, **RSI** **<** **45**, **resistance** **pullback**
- [ ] **VIX** **15–30** **at** **open**, **cached**
- [ ] **Optional** **earnings** **gates**
- [ ] **Capital** **$30,000** / **SIM3236523M**

---

*End of specification — Strategy 004 v0.2.0*

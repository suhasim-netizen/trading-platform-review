---
id: strategy_001
name: Equity Momentum S&P 500
version: 0.1.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.strategy_001
asset_class: equity
status: paper
---

# Strategy 001 — Equity Momentum (S&P 500)

## Document control

| Field | Value |
|--------|--------|
| **Strategy slug** | `strategy_001_equity_momentum_sp500` |
| **Semantic version** | `0.1.0` |
| **Owner** | `platform` (Director-owned) |
| **Tenant** | `director` |
| **Status** | `paper` |
| **Asset class** | `us_equities` |
| **Specification status** | Draft — ready for backtesting handoff |
| **Last updated** | 2026-04-12 |

---

## 1. Strategy identity

### 1.1 Name and purpose

**Name:** Equity Momentum — S&P 500

**Purpose:** Systematic **cross-sectional momentum** on US large-cap equities: rank S&P 500 constituents by **12–1 month** formation returns (twelve months of past return **excluding** the most recent month), hold a concentrated **equal-weight** long-only portfolio with a **liquidity-screened** universe and a **VIX** risk-off overlay.

### 1.2 Versioning and ownership

- **Version:** `0.1.0`
- **Owner:** `platform` — not tenant-authored; IP remains with the Director per ADR 0003.
- **Tenant:** `director` — research, configs, and paper runs scoped to `tenant_id = director` unless entitlements extend to other tenants.

### 1.3 Deployment

- **Target:** **Paper trading** first under `tenant_id = director`.
- **Live:** Out of scope until paper validation, risk review, and operational gates.

---

## 2. Universe and data

### 2.1 Universe

- **Benchmark membership:** Current **S&P 500** constituents (point-in-time preferred for backtests; as-of rebalance date if survivorship-bias-free data unavailable — document assumption).
- **Liquidity screen:** Restrict to the **top 100** names by **trailing 63-trading-day median daily dollar volume** (price × volume) as of **t** (rebalance decision date). **Minimum:** exclude names with **median dollar volume below platform floor** (e.g. $5M/day — set with Data Engineer).
- **Listing:** US-listed common equity; **exclude** ADRs if policy requires pure domestic (default: **include** S&P ADRs if in index).

### 2.2 Data frequency and fields

- **Bar frequency:** **Daily** OHLCV, **regular trading hours** close (align with Data Engineer; single session definition).
- **Required fields:** `date`, `open`, `high`, `low`, `close`, `volume`, `symbol`, corporate-action fields for **total-return** or **split-adjusted** prices for return calculation.
- **Minimum history:** **≥ 3 years** of daily OHLCV per symbol for production-quality backtests; **273+** trading days before first signal date for 12–1 warmup (see §7).

### 2.3 Constituents and corporate actions

- **Splits/dividends:** Use **split-adjusted** close for return math; total-return series preferred if available.
- **Index changes:** Point-in-time index membership strongly preferred to avoid lookahead.

### 2.4 External series

- **VIX:** CBOE VIX **daily close**, aligned to **US equity** session date for regime filter (§5).

---

## 3. Signals

### 3.1 Cross-sectional 12–1 momentum

For each stock **i** in the investable universe at **t** (monthly rebalance, §3.4), using **split-adjusted** close **P**:

Define **S = 21** trading days (~1 month skip) and **L = 252** trading days (~12 months).

**12–1 formation return:**

\[
R^{12-1}_{i,t} = \frac{P_{i,t-S}}{P_{i,t-S-L}} - 1 = \frac{P_{i,t-21}}{P_{i,t-273}} - 1
\]

- **Missing/bad data:** If denominator ≤ 0 or missing, **exclude** stock **i** from ranking that month; log.

**Rank:** Sort eligible stocks by \(R^{12-1}_{i,t}\) **descending**; **rank 1** = strongest momentum.

### 3.2 Entry

When **regime ON** (§5):

1. Build ranked list from §3.1 on universe **§2.1**.
2. **Initial / add:** Allocate capital to the **top 10** names by rank (subject to §4). **Equal weight** each position at rebalance.
3. **Capacity:** If fewer than 10 names pass data quality, hold **all** that pass up to 10 (document thin edge case).

### 3.3 Exit and rebalance (monthly)

**Rebalance cadence:** **Monthly**, decision on **last trading day of month** (close); **execution** default **next session open** (or VWAP first hour — parameter for Backtesting Engineer).

**Per-name exit:** **Sell** any held stock whose **momentum rank** at **t** is **worse than 20** (i.e. **rank ≥ 21** among eligible universe at **t**).

**Portfolio refresh:**

- After applying exits, **refill** slots by purchasing names in **rank order** from the current **top 10** set not yet held until **10 positions** or investable set exhausted.
- **Re-equalize** to **equal weight** across all **held** positions at rebalance (subject to **10% per name cap**, §4).

**Regime OFF:** **Liquidate all** equity positions (next open or same close per sim convention); **no new entries** until regime ON.

### 3.4 Confirmation filters (optional, default off)

| ID | Description | Default |
|----|-------------|---------|
| F1 | Minimum price filter (e.g. > $5) | Off |
| F2 | Sector cap | Off in v0.1.0 |

---

## 4. Position sizing

### 4.1 Method

- **Base:** **Equal weight** across **held** positions at each monthly rebalance.
- **Max per position:** **10%** of strategy **allocated** equity **notional** per name (with **10** names → **~100%** gross long exposure before cash drag).
- **Cash:** Residual from partial fills or rounding remains **cash** until next rebalance.

### 4.2 Limits

- **Max concurrent positions:** **10** longs.
- **Max gross exposure:** **100%** of strategy sleeve (long-only v0.1.0).
- **Leverage:** **None** in v0.1.0.

---

## 5. Market regime conditions

### 5.1 Regime filter (VIX)

- **Strategy OFF (risk-off):** When **VIX_t > 30** at the **daily close** used for regime (same date as rebalance decision or prior session — **default:** **prior session close** VIX to avoid lookahead on same-day close if rebalance uses EOD equity).

**Recommended default:** Use **VIX at close of T−1** relative to rebalance decision **T** for the monthly signal.

- **Strategy ON:** **VIX ≤ 30** — entries and **maintenance** rebalances allowed.

### 5.2 When VIX missing

- **Fail closed:** **OFF** — no new entries; **flatten** if policy requires; **log** gap.

---

## 6. Risk profile

### 6.1 Expected performance (literature-informed, not a guarantee)

- **Sharpe:** Academic cross-sectional momentum (e.g. Jegadeesh–Titman lineage) often reports **gross** Sharpe in rough range **0.8–1.2** in classic samples; **net of costs** and **post-2008** weaker; use **walk-forward** validation (§7).
- **Max drawdown:** **20%–30%** plausible for concentrated long-only momentum sleeves; **stress** beyond 30% in crisis regimes.

### 6.2 Known failure modes

| Mode | Notes |
|------|--------|
| **Momentum crashes** | Sharp reversals after extended trends; VIX overlay mitigates but does not eliminate |
| **Crowding** | Popular factor; capacity and correlation risk |
| **Turnover / costs** | Monthly rebalance + rank 20 exit band — tune with realistic commissions/slippage |
| **Data / survivorship** | PIT membership and adjustment assumptions materially affect results |
| **Liquidity** | Top-100 dollar volume may still stress in stressed markets |

---

## 7. Backtesting requirements

### 7.1 Data

- **Minimum:** **3 years** daily OHLCV + **S&P 500 constituents** history (PIT preferred).
- **VIX:** Full overlap with equity window.

### 7.2 Costs

- **Commissions:** Per share / per order from broker sim.
- **Slippage:** Baseline **5–10 bps** per side on notional (sensitivity analysis).

### 7.3 Parameters to optimise (bounded)

| Parameter | Initial search |
|-----------|----------------|
| Universe size (liquidity cut) | 75, 100, 125 |
| Portfolio size (top N) | 8, 10, 12 |
| Exit rank threshold | 15, 20, 25 |
| VIX cutoff | 28, 30, 32 |

### 7.4 Walk-forward

- **Split:** e.g. **80% in-sample** / **20% out-of-sample** or **rolling** 3y train / 1y test.
- **Gates:** Align with platform rules — iterate if **Sharpe < 0.8** or **max DD > 25%** OOS net of costs.

---

## 8. Handoff checklist (Quant → Backtesting Engineer)

- [ ] Owner: **platform**; tenant: **director**; version: **0.1.0**; status: **paper**; asset_class: **us_equities**
- [ ] Universe: S&P 500 → **top 100** by liquidity
- [ ] Signal: **12–1** \(R = P_{t-21}/P_{t-273} - 1\), cross-sectional rank
- [ ] Entry: **Top 10** equal weight
- [ ] Exit: Monthly; drop if rank **> 20**; refill toward top 10
- [ ] Regime: **OFF** if **VIX > 30**
- [ ] Data: **≥3y** daily OHLCV + constituents + VIX

---

## 9. References (non-exhaustive)

- Jegadeesh, N., & Titman, S. (1993). *Returns to buying winners and selling losers.* Journal of Finance, 48(1), 65–91.  
- Jegadeesh, N., & Titman, S. (2001). *Profitability of momentum strategies.* Journal of Finance, 56(3), 873–899.  
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). *Time series momentum.* Journal of Financial Economics, 104(2), 228–250.  

---

*End of specification — Strategy 001 v0.1.0 (Equity Momentum — S&P 500)*

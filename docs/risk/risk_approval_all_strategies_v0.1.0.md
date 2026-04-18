# Risk Approval — All Strategies v0.1.0 (Paper Trading)

**Date:** 2026-04-16  
**Tenant:** `director`  

Two **simulation accounts**; strategies and telemetry remain **scoped by account binding + `tenant_id`** — no cross-account mixing.

---

## Account map & capital

| Account ID | Asset scope | Total capital | Strategies |
|------------|-------------|--------------:|------------|
| **SIM3236523M** | Equities + options | **$50,000** | 002, 003, 004, 005 |
| **SIM3236524F** | Futures only | **$50,000** | 006 |

### Per-strategy sleeves (paper)

| Strategy | Account | Sleeve | Notes |
|----------|---------|--------:|-------|
| **002** — Equity momentum | SIM3236523M | **$20,000** | |
| **003** — Equity intraday (ORB) | SIM3236523M | **$20,000** | **PDT N/A** (see below) |
| **004** — Equity swing | SIM3236523M | **$7,000** | |
| **005** — Options intraday | SIM3236523M | **$3,000** | Premium scaled to sleeve |
| **006** — Futures intraday | SIM3236524F | **$50,000** | **ES/NQ** standard contracts |

---

## PDT (Strategy 003)

**Account SIM3236523M equity capital is $50,000 — above the $25,000 PDT threshold.** For this deployment, **Pattern Day Trader rules do not restrict** day trading in equities.

**Risk posture:** **Do not** block entries using **PDT** / **three round-trips in five days** / **`can_day_trade()` for PDT reasons** on this account. (Optional: keep **operational** day-trade counters for telemetry only — **no** order suppression for PDT.)

Tech Lead / implementation: remove or bypass PDT enforcement for **003** when bound to **SIM3236523M**; if code remains shared with sub-$25k accounts, gate PDT logic on **account equity &lt; $25,000** only.

---

## Portfolio-level risk (by account)

| # | Scope | Limit | Rationale |
|---|--------|-------|-----------|
| **5** | **Account 1 (SIM3236523M)** — combined equities + options | **Halt all new entries** on Account 1 for the remainder of the session if **combined realized + mark-to-market P&amp;L** for **002+003+004+005** ≤ **−$1,500** (**−3.0%** of $50k) | Correlated risk across sleeves; manage open risk per strategy unless a strategy-level pause fires. **Reset** next session unless extended. |
| **6** | **Account 2 (SIM3236524F)** — futures only — daily loss limit | **Halt all new futures entries** if **daily P&amp;L** ≤ **−$2,000** (**−4.0%** of $50k) | Stops new risk before the account reaches the **5%** floor in item **7**; applies to **new** orders only — existing **006** positions can still move MTM. |
| **7** | **Account 2 (SIM3236524F)** — mandatory breaker | If Account 2 **realized + MTM** loss for the day **≥ $2,500** (**5%** of $50k), **halt all new futures entries** and **escalate** to Director/Orchestrator (session may still show deeper MTM from open contracts until flat) | User-specified **5%** line; **operational** interpretation: item **6** should prevent **new** entries from pushing past **−$2k**; item **7** is the **non-negotiable** daily loss ceiling for **account health** and **escalation**. |

**Note:** Items **6** and **7** work together: **earlier** halt of **new** entries at **−$2,000**; **mandatory** account-level response and escalation at **−$2,500** total day P&amp;L.

---

## Strategy 002 — Equity momentum

**Status: APPROVED FOR PAPER TRADING**

| # | Limit | Value |
|---|--------|-------|
| 1 | **Max position size** | **≤ $10,000** notional per name; **≤ 2** concurrent positions; **≤ $20,000** gross (equal weight when two open). |
| 2 | **Max drawdown trigger** | **−22%** peak-to-trough on strategy sleeve NAV (**−$4,400** on $20k) — **pause** strategy (no new entries; manage open per spec). |
| 3 | **Daily loss limit** | **−2.5%** of sleeve (**−$500** / day on $20k). |
| 4 | **Strategy-specific** | **VIX(T−1 close) &gt; 28:** no **new** entries. **8%** stop from **P₀**. Max **2** positions — no third entry. |

---

## Strategy 003 — Equity intraday (ORB)

**Status: APPROVED FOR PAPER TRADING** ( **no PDT constraint** on SIM3236523M )

| # | Limit | Value |
|---|--------|-------|
| 1 | **Max position size** | **Risk $200/trade** (**1%** of $20k sleeve); **1** position per symbol; **shares = floor($200 / \|entry − OR stop\|)** with minimum **OR width** / **ε** guards per spec. |
| 2 | **Max drawdown trigger** | **−18%** on sleeve (**−$3,600** on $20k). |
| 3 | **Daily loss limit** | **−4%** of sleeve (**−$800** / day) **or** **10** full **$200** stop-outs (**−$2,000**) same session — **whichever first** (backstop for repeated stops). |
| 4 | **Strategy-specific** | **Flat 15:55 ET.** No new entries after **14:00 ET.** **PDT:** **not enforced** on **SIM3236523M** (equity **≥ $25k**). Shorts: **margin/locate** via **BrokerAdapter** only. |

---

## Strategy 004 — Equity swing

**Status: APPROVED FOR PAPER TRADING**

| # | Limit | Value |
|---|--------|-------|
| 1 | **Max position size** | **≤ $3,500** notional per position; **≤ 2** concurrent; **≤ $7,000** gross. |
| 2 | **Max drawdown trigger** | **−20%** on sleeve (**−$1,400** on $7k). |
| 3 | **Daily loss limit** | **−3%** of sleeve (**−$210** / day). |
| 4 | **Strategy-specific** | **TP +8%**, **stop −4%**, **time exit** day **10** per spec. |

---

## Strategy 005 — Options intraday

**Status: APPROVED FOR PAPER TRADING**

Spec §6 uses **$500 / trade** and **$1,500** total premium — **too large** for a **$3,000** sleeve (**50%** of capital if fully deployed).

| # | Limit | Value |
|---|--------|-------|
| 1 | **Max position size** | **≤ $350** debit per opening trade; **≤ 3** concurrent positions; **≤ $900** total entry premium deployed (**30%** of $3k). **1** open position per underlying. |
| 2 | **Max drawdown trigger** | **−40%** on sleeve (**−$1,200** on $3k) — options path risk. |
| 3 | **Daily loss limit** | **−10%** of sleeve (**−$300** / day). |
| 4 | **Strategy-specific** | **Flat 15:45 ET.** No entries after **15:30 ET.** **Stop −50%** / **target +100%** on premium. Skip wide spreads per execution threshold. |

---

## Strategy 006 — Futures intraday (VWAP ± ATR)

**Status: APPROVED FOR PAPER TRADING**

**Sizing (SIM3236524F, $50k):** Standard **ES** and **NQ** contracts are **appropriate**. **Paper phase:** start **1 × ES** and **1 × NQ** maximum **net** at a time (one line each); **do not** exceed **2** contracts **per instrument** per **entry sequence** after validation — **cap at 2 ES and 2 NQ** total net exposure (Risk Manager: **max 1 + 1 for paper** until PM extends).

| # | Limit | Value |
|---|--------|-------|
| 1 | **Max position size** | **Paper:** **1** contract **ES** max net; **1** contract **NQ** max net (independent legs). **Post-paper (documented bump):** up to **2 ES** and **2 NQ** per risk addendum. **No pyramiding** beyond caps. |
| 2 | **Max drawdown trigger** | **−20%** on futures sleeve (**−$10,000** on $50k). |
| 3 | **Daily loss limit** | **−4%** of sleeve (**−$2,000** / day) — aligns with Account 2 halt in §Portfolio-level item **6**. |
| 4 | **Strategy-specific** | **Flat 15:55 ET.** Stop **0.5%**; target **±0.75%** from entry. Monitor **margin** and **span** intraday. **Account 2:** halt new entries per **−$2,000** daily and **−$2,500** breaker (§items 6–7). |

---

## Summary sign-off

| Strategy | Account | Decision |
|----------|---------|----------|
| 002 | SIM3236523M | **APPROVED FOR PAPER TRADING** |
| 003 | SIM3236523M | **APPROVED FOR PAPER TRADING** (PDT **not applied**) |
| 004 | SIM3236523M | **APPROVED FOR PAPER TRADING** |
| 005 | SIM3236523M | **APPROVED FOR PAPER TRADING** (scaled premium vs $3k sleeve) |
| 006 | SIM3236524F | **APPROVED FOR PAPER TRADING** (ES/NQ; **1+1** contracts paper) |

**Risk Manager — 2026-04-16**

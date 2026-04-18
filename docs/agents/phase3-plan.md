# Phase 3 — Multi-Strategy Expansion (3A & 3B Only)

**Orchestrator context:** Expand from one placeholder strategy to a **multi-strategy** platform. This document covers **Phase 3A** (fix `strategy_001`, add **Equity Momentum** `strategy_002`) and **Phase 3B** (add **Futures Intraday** `strategy_006` on `@ES` / `@NQ`). Phases 3C–3E are **out of scope** here except where noted as downstream dependencies.

**Canonical path:** This file lives at `docs/agents/phase3-plan.md` (Orchestrator checklist).

**Confirmed operating assumptions (Director):**

| Item | Value |
|------|--------|
| Execution | Fully automated, **regular hours 9:30am–4:00pm ET** |
| Capital | **&lt; $50,000** total across strategies |
| Equity + options account | `SIM3236523M` |
| Futures account | `SIM3236524F` |
| Momentum universe (weeks) | AVGO, LLY, TSM, GEV |
| Futures intraday | `@ES`, `@NQ` |

**Infrastructure from the master list in scope for 3A/3B:**

| Gap | In 3A/3B plan? |
|-----|----------------|
| 5-minute bar feed | **Yes** (required for 3B; supports future 3C) |
| Multi-symbol scanner / batch subscribe | **Yes** |
| Intraday position manager (flatten before **3:55pm ET**) | **Yes** (required for 3B) |
| PDT rule tracker | **Implement in 3A infra**; **not** a hard gate for futures in 3B (PDT exempt). **Hard gate** before Phase 3C equity intraday (documented dependency only). |
| Options chain `BrokerAdapter` extension | **No** in this file (Phase 3E). |
| Market session calendar | **Yes** |

---

## Numbered tasks — Phase 3A & 3B

### Task 1 — Market session calendar (US equities + futures RTH)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/market/` (or agreed package): **NYSE/NASDAQ regular session** 9:30–16:00 **ET**, holiday / early-close handling (data source documented: exchange calendar file, `exchange_calendars`, or manual JSON for SIM phase).  
  - Futures: CME equity index session window for `@ES` / `@NQ` aligned to automation window (document assumptions for SIM).  
  - Helper API: `is_open_now()`, `next_open()`, `minutes_to_session_close()` used by orchestrator and flatten job.  
  - Unit tests with fixed dates (no network).  
  - `docs/market_calendar_phase3.md` — rules, limitations, how to update holidays.  
- **Dependency:** Phase 2 exit criteria (or Phase 1+2 broker + config patterns) met; `Settings` can hold timezone default `America/New_York`.  
- **Status:** [ ] Not started  

---

### Task 2 — 5-minute bar feed (aggregate from streaming or poll)

- **Agent:** Data Engineer (+ Tech Lead for `BrokerAdapter` hooks)  
- **Deliverable:**  
  - Pipeline producing **5m OHLCV bars** per symbol, clock in **ET**, bar boundary aligned to wall-clock 5m (document alignment vs exchange session).  
  - Backfill or warm-up policy for service restart (document).  
  - Storage optional for Phase 3 (in-memory ring + last N bars per symbol acceptable if documented); **no cross-tenant leakage** if multi-tenant DB used.  
  - `tests/unit/` + `tests/integration/` for bar boundaries and multi-symbol concurrency (mocked feeds).  
  - `docs/bars_5m_pipeline.md` — inputs, outputs, failure modes.  
- **Dependency:** Task 1 (session awareness for bar validity); streaming or REST from existing TradeStation adapter (Phase 2) extended minimally for historical/intraday bars if needed.  
- **Status:** [ ] Not started  

---

### Task 3 — Multi-symbol scanner / subscription manager

- **Agent:** Tech Lead  
- **Deliverable:**  
  - Component that accepts a **list of symbols** (≥ **20** concurrent for future phases), subscribes via broker streaming or batched REST per rate limits, and exposes a **single interface** to strategies (e.g. `subscribe(symbols) -> async iterator of events` or callback registry).  
  - Rate-limit and reconnect behavior documented; **tenant-scoped** if multiple tenants share infra (align with Phase 1 `tenant_id`).  
  - `tests/` with mocks; load test optional (document cap).  
  - `docs/multi_symbol_scanner.md` — caps, TradeStation-specific notes confined to `tradestation/` package.  
- **Dependency:** Task 2 (or explicit contract that scanner feeds bar builder + raw quotes); Phase 2 streaming adapter stable.  
- **Status:** [ ] Not started  

---

### Task 4 — Intraday position manager (mandatory flatten before 3:55pm ET)

- **Agent:** Tech Lead (+ Risk Manager for policy wording)  
- **Deliverable:**  
  - Scheduled job / asyncio task: **before 3:55pm ET** on session days, **flatten all open intraday positions** for configured strategies/accounts per rules (futures + later equities).  
  - Interaction with OMS: cancel open orders + flatten; **idempotent** if run twice.  
  - Config: `FLATTEN_TIME_ET=15:55` (or equivalent), per-strategy overrides if needed (document).  
  - `docs/intraday_flatten.md` — scope (which accounts: `SIM3236524F` for 3B), exceptions, manual override procedure for Director.  
  - Tests: time-mocked scenarios.  
- **Dependency:** Task 1; broker `place_order` / `get_positions` / `cancel_order` working for futures account in paper/sim; account routing (Task 7).  
- **Status:** [ ] Not started  

---

### Task 5 — PDT rule tracker (equity day trades; futures exempt)

- **Agent:** Tech Lead (+ App Architect for data model review)  
- **Deliverable:**  
  - Persistent store (DB table or tenant-scoped ledger): rolling **5 business days** window, count **day trades** per **equity** account `SIM3236523M` (definition: buy+sell same symbol same day per FINRA pattern day trader rules — document exact definition used in code).  
  - **Block** new opening equity day trades when count ≥ **3** and **equity** &lt; **$25,000** (configurable thresholds to match Director capital — **note:** total capital &lt; $50K; wire **account equity** from broker `get_account` if available, else conservative guard).  
  - **Futures orders must not increment PDT counter** (`strategy_006` / `@ES` `@NQ` on `SIM3236524F`).  
  - API/hook: `can_open_day_trade(tenant_id, account_id, symbol, instrument_type) -> bool` used later by 3C; for 3A/3B implement + test even if 3A strategies do not day trade.  
  - `docs/pdt_tracker.md` — definitions, thresholds, bypass for futures/options indices.  
  - Unit tests for rolling window and futures exemption.  
- **Dependency:** Task 1 (session days); DB from Phase 1; account metadata distinguishes futures vs equity account.  
- **Status:** [ ] Not started  

---

### Task 6 — Multi-strategy orchestrator & capital budget (&lt;$50K)

- **Agent:** Tech Lead (+ Portfolio Manager for allocation policy)  
- **Deliverable:**  
  - Orchestrator runs **multiple strategies** with a **global capital budget** (config: `MAX_TOTAL_CAPITAL_USD=50000`) and per-strategy caps for 3A/3B (document defaults).  
  - No strategy may exceed its allocation; **sum ≤** global cap.  
  - Logging/metrics: per-strategy P&amp;L placeholder, exposure snapshot.  
  - `docs/capital_allocation_phase3.md`.  
- **Dependency:** Phase 1/2 execution path exists; `Settings` extended.  
- **Status:** [ ] Not started  

---

### Task 7 — Broker account routing (SIM3236523M vs SIM3236524F)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - Config mapping: equity/options strategies → account id **SIM3236523M**; futures strategies → **SIM3236524F**.  
  - Enforced in OMS / `place_order` path: **reject** orders sent to wrong account for instrument class (e.g. futures contract on equity account).  
  - `.env.example` keys documented; **no secrets**.  
  - Tests: routing table + rejection cases.  
- **Dependency:** `get_account` / account list from broker or static config for SIM (document).  
- **Status:** [ ] Not started  

---

### Task 8 — Fix `strategy_001` (placeholder → production-ready baseline)

- **Agent:** Tech Lead (+ Quant Analyst if logic/spec changes)  
- **Deliverable:**  
  - `src/strategies/` — repair `strategy_001` per issues backlog (document what “fix” means in `docs/strategy_001_changelog.md`): stable interface to orchestrator, correct symbol list wiring, session + capital checks, **no trades outside RTH** per Task 1.  
  - Unit tests; strategy registered with **owner = platform**.  
- **Orchestrator checklist — DB seed (after spec or production change):**  
  - Run: `python scripts/seed_strategies.py`  
  - Verify `strategy_001` appears in the `strategies` table.  
- **Dependency:** Tasks 1, 6, 7; bar feed if `strategy_001` is intraday (if not, document daily data source).  
- **Status:** [ ] Not started  

---

### Task 9 — Add `strategy_002` — Equity Momentum (hold weeks)

- **Agent:** Quant Analyst (spec) + Tech Lead (implementation)  
- **Deliverable:**  
  - `docs/strategies/` — Quant Analyst writes the spec (e.g. `strategy_002_v0.1.0.md`) with YAML frontmatter; rules, parameters, universe **AVGO, LLY, TSM, GEV**, rebalance frequency, risk per position, **exit** rules.  
  - Code: `src/strategies/...` implementing spec; uses **SIM3236523M**; **no overnight intraday scalping**; holds **weeks** horizon per Director.  
  - Backtest or research notebook optional (path documented); minimum: **paper/SIM validation** checklist.  
  - Registered in strategy registry with priority **Phase 3A** relative to `strategy_001`.  
- **Orchestrator checklist — DB seed (after Quant Analyst writes or updates spec):**  
  - Run: `python scripts/seed_strategies.py`  
  - Verify `strategy_002` appears in the `strategies` table.  
- **Dependency:** Tasks 1, 6, 7, 8 (baseline orchestration stable); daily/weekly bar or EOD data path agreed (may not require Task 2 if momentum uses daily only — **explicitly document** data frequency in spec).  
- **Status:** [ ] Not started  

---

### Task 10 — Add `strategy_006` — Futures intraday (`@ES`, `@NQ`)

- **Agent:** Quant Analyst (spec) + Tech Lead (implementation)  
- **Deliverable:**  
  - `docs/strategies/` — Quant Analyst writes the spec (e.g. `strategy_006_v0.1.0.md`) with YAML frontmatter — entry/exit, max trades/day, position sizing vs allocation on **SIM3236524F**, **PDT N/A**.  
  - Code uses **5m bars** from Task 2 and **multi-symbol** Task 3 for `@ES` + `@NQ`; **flatten** integrated with Task 4 before **3:55pm ET**.  
  - Futures contract specs (front month roll rule or fixed contract — document).  
  - Tests with mocks; SIM validation runbook `docs/strategy_006_sim_runbook.md`.  
- **Orchestrator checklist — DB seed (after Quant Analyst writes or updates spec):**  
  - Run: `python scripts/seed_strategies.py`  
  - Verify `strategy_006` appears in the `strategies` table.  
- **Dependency:** Tasks 1–4, 6, 7; Task 5 must **not** block futures path (verify exemption in tests); Phase 2 full adapter for futures orders if not already complete.  
- **Status:** [ ] Not started  

---

### Task 11 — Phase 3A / 3B QA & Director sign-off

- **Agent:** QA Engineer  
- **Deliverable:**  
  - `docs/qa/phase3a3b_signoff.md` — date, commit SHA, evidence: RTH-only behavior, flatten before 3:55pm, account routing correct, capital caps enforced, `strategy_001` + `strategy_002` + `strategy_006` on correct SIM accounts, **no live production capital** unless Director opts in.  
  - Automated test summary attached.  
- **Dependency:** Tasks 1–10 complete and merged.  
- **Status:** [ ] Not started  

---

## Dependency graph (summary)

```
Task 1 (calendar)
   └─► Task 2 (5m bars) ─► Task 3 (scanner) ─► Task 10 (strategy_006)
   └─► Task 4 (flatten) ────────────────────────────► Task 10
Task 5 (PDT) ─► (gates 3C later; must not block Task 10)
Task 6 (orchestrator/capital) ─► Task 8, 9, 10
Task 7 (account routing) ─► Task 8, 9, 10
Task 8 (strategy_001 fix) ─► Task 9 (strategy_002)
```

---

## Phase 3A & 3B exit criteria

- [ ] **Calendar:** No orders placed outside **9:30–4:00 ET** regular session per Task 1 (documented exceptions: none for Phase 3A/3B unless Director approves).  
- [ ] **5m bars + scanner:** AVGO/LLY/TSM/GEV and `@ES`/`@NQ` receive timely bars/quotes per SLO in `docs/bars_5m_pipeline.md` / `docs/multi_symbol_scanner.md`.  
- [ ] **Flatten:** All intraday futures (and any intraday equity in scope) **flat by 3:55pm ET** in tests and SIM dry-run evidence.  
- [ ] **PDT:** Tracker implemented; **futures** path verified **not** incrementing PDT; equity path ready for 3C.  
- [ ] **Capital:** Global **&lt; $50K** and per-strategy caps enforced in orchestrator.  
- [ ] **Accounts:** `SIM3236523M` used for equity strategies; `SIM3236524F` for `@ES`/`@NQ` only; mis-routing **rejected** in code.  
- [ ] **Strategies:** `strategy_001` fixed; `strategy_002` momentum live in SIM per spec; `strategy_006` futures intraday live in SIM per spec.  
- [ ] **QA:** `docs/qa/phase3a3b_signoff.md` completed.  

---

## Explicitly deferred (not in this document)

- **Options chain** `BrokerAdapter` extension — Phase **3E**.  
- **Phase 3C–3E** strategies (`strategy_003` intraday equity, `strategy_004` swing, `strategy_005` options) — separate plan after 3A/3B exit.  

---

*Maintained by: Director + Orchestrator. Phase 3A/3B task plan.*

# Phase 2 — Live Data, Full Adapter, First Strategy, Paper Trading

**Goal:** Complete the TradeStation `BrokerAdapter` (REST + streaming), stand up a **real-time market-data pipeline** into the core engine, **design and backtest** the **first platform-owned strategy**, then run it end-to-end against **TradeStation paper trading** (no live capital in Phase 2 unless Director explicitly escalates).

**Assumed complete:** Phase 1 exit criteria met; QA sign-off **2026-04-15**; `BrokerAdapter` contract, auth, DB tenant scoping, security baseline, and registry/factory in place.

**Parallel work (summary):** Tasks marked **(∥)** can run in parallel with others *once their “Depends on” minimum is satisfied* — see **Parallel tracks** at the bottom.

---

## Phase 2 — Live Data, Full Adapter, First Strategy, Paper Trading

### Task P2-01 — TradeStation REST adapter completion (non-streaming)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/brokers/tradestation/` — REST implementation for: `get_quote`, `get_account`, `get_positions`, `place_order`, `cancel_order` (map TS responses ↔ `src/brokers/models.py`)  
  - Shared HTTP client module (timeouts, retries, auth header injection from `AuthToken`) — exact path per repo convention (e.g. `rest.py` / `client.py`)  
  - Unit tests with **mocked HTTP** (`tests/unit/brokers/tradestation/…`)  
  - `docs/tradestation_rest_mapping.md` — endpoint ↔ method mapping, error code → `BrokerError` mapping table  
- **Depends on:** Phase 1 complete (auth, `BrokerAdapter` contract, factory wiring)  
- **Security review required:** yes (external API calls, order endpoints, credential use)  
- **Status:** [ ] Not started  

---

### Task P2-02 — TradeStation streaming adapter (quotes + order updates)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/brokers/tradestation/` — implementations of `stream_quotes` and `stream_order_updates` (`AsyncIterator` of platform `Quote` / `OrderUpdate`)  
  - Reconnection/backoff strategy; subscription lifecycle documented  
  - Tests with mocked websocket or recorded fixtures (`tests/unit/…` or `tests/integration/…`)  
  - `docs/tradestation_streaming.md` — subscribe/auth flow, heartbeat, reconnect, known limits  
- **Depends on:** P2-01 (HTTP/auth patterns and error mapping stable)  
- **Security review required:** yes (live connections, tokens on wire — confirm TLS/wss only; no token logging)  
- **Status:** [ ] Not started  

---

### Task P2-03 — Real-time market data pipeline

- **Agent:** Data Engineer (+ Tech Lead for interface glue)  
- **Deliverable:**  
  - Pipeline: broker stream → normalize → **tenant-scoped** fan-out to consumers (in-process and/or Redis/pub-sub — exact choice documented)  
  - Config-driven symbols/universe for Phase 2 (`Settings` + `.env.example` keys)  
  - Optional short retention / ring buffer for debugging (no PII; document TTL)  
  - `tests/integration/` — pipeline receives mocked adapter stream; **no cross-tenant leakage**  
  - `docs/market_data_pipeline.md` — diagram + failure modes + backpressure  
- **Depends on:** P2-02 (or frozen `Quote` / stream contract + stub stream for early integration)  
- **Security review required:** yes (if Redis/network or new secrets; no if purely in-process mocks only — **default yes** once Redis/external bus used)  
- **Status:** [ ] Not started  
- **(∥)** Can overlap **late** with P2-04 / P2-05 once stream contract and strategy data needs are agreed (see Parallel tracks).

---

### Task P2-04 — First platform strategy specification

- **Agent:** Quant Analyst  
- **Deliverable:**  
  - `docs/strategies/platform_strategy_v1.md` — hypothesis, instruments, timeframe, entry/exit, risk limits, parameters, **paper-trading validation criteria**  
  - Input/output contract: which fields from `Quote`/bars strategy consumes; signal frequency  
  - Explicit **non-goals** for Phase 2 (e.g. no options, no multi-tenant client strategies)  
- **Depends on:** Phase 1 strategy registry stub; agreed market-data fields from `brokers/models.py` (coordinate with Tech Lead)  
- **Security review required:** no  
- **Status:** [ ] Not started  
- **(∥)** Can start **early** in parallel with P2-01 once data contracts are frozen (short alignment meeting or shared doc).

---

### Task P2-05 — Backtesting harness + historical data path

- **Agent:** Tech Lead (+ Quant Analyst for acceptance criteria)  
- **Deliverable:**  
  - `src/data/historical.py` (or agreed module) — load/cache bars for backtest; interface **broker-agnostic** (CSV/Parquet/API stub)  
  - `src/backtest/` (or `src/core/backtest/`) — engine: signals → simulated fills with costs/slippage assumptions documented  
  - `tests/unit/backtest/…` — deterministic tests on fixed fixture data  
  - `docs/backtest_methodology.md` — assumptions, limitations, what “pass” means for Phase 2  
- **Depends on:** P2-04 (strategy spec stable enough to freeze inputs/outputs); `Order` / `Position` models from Phase 1  
- **Security review required:** no (offline data path; no live keys)  
- **Status:** [ ] Not started  

---

### Task P2-06 — Implement Strategy V1 (platform-owned)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/strategies/platform/` (or agreed package) — code implementing **P2-04** spec; registered in `src/strategies/registry.py` with **owner = platform**  
  - Parameterization via config/env; **no hardcoded tenant other than tests**  
  - Unit tests for strategy logic (pure functions where possible)  
- **Depends on:** P2-04, P2-05 (or parallel if strategy is simple — minimum: spec approved by Director)  
- **Security review required:** no (logic only; no new external calls inside strategy code)  
- **Status:** [ ] Not started  

---

### Task P2-07 — Paper trading configuration & execution safety

- **Agent:** Tech Lead (+ Security Architect review)  
- **Deliverable:**  
  - Explicit **paper vs live** mode in `Settings` (e.g. `TRADING_MODE=paper|live`); **default paper** for Phase 2  
  - Broker account id / paper endpoint selection **only** via config; block live placement if `TRADING_MODE=paper` mismatch (defensive check)  
  - `docs/paper_trading.md` — how Director verifies paper account in TradeStation UI; kill-switch env flag  
  - Update `.env.example` with paper-trading variables (no secrets)  
- **Depends on:** P2-01 (order path exists); Phase 1 security baseline  
- **Security review required:** yes (misconfiguration could send live orders — **mandatory** before any run)  
- **Status:** [ ] Not started  

---

### Task P2-08 — Live integration: pipeline + strategy → OMS → paper orders

- **Agent:** Tech Lead  
- **Deliverable:**  
  - End-to-end path: market data pipeline → strategy decision → `place_order` via `BrokerAdapter` factory → persistence (orders table) with `tenant_id`  
  - Idempotency / duplicate signal handling documented (at least stub or minimal guard)  
  - `tests/integration/test_paper_trading_flow.py` (mocked broker or paper sandbox — **no live** secrets in CI)  
  - `docs/runbook_phase2_paper.md` — exact startup order, env vars, how to stop safely  
- **Depends on:** P2-03, P2-06, P2-07, P2-01  
- **Security review required:** yes (full order path; tenant scope; logging redaction)  
- **Status:** [ ] Not started  

---

### Task P2-09 — Risk & limits (pre-trade) for paper session

- **Agent:** Risk Manager (+ Tech Lead implementation)  
- **Deliverable:**  
  - Configurable limits: max order size, max daily loss/notional, max open orders (values **paper-appropriate**)  
  - Enforcement point **before** `place_order`; violations logged and blocked  
  - `docs/risk_limits_phase2.md` — limit semantics + who can change constants  
  - Tests for limit breaches  
- **Depends on:** P2-08 wiring exists (can stub limits earlier if needed)  
- **Security review required:** no (business logic; no new secrets) — **yes** if limits touch authz between tenants (future); for single-tenant paper, **no**  
- **Status:** [ ] Not started  
- **(∥)** Can start spec in parallel with P2-06; implementation best after P2-08 skeleton.

---

### Task P2-10 — Observability & operational readiness

- **Agent:** Tech Lead  
- **Deliverable:**  
  - Structured logging for: data feed health, strategy signals (counts only), order submit/ack/fill (no tokens)  
  - Metrics hooks or documented placeholders (latency, reconnects) — match existing stack  
  - `README.md` / `docs/operations_phase2.md` — how Director monitors a paper session  
- **Depends on:** P2-08 (meaningful log points)  
- **Security review required:** yes (log redaction review — ensure no PII/secrets)  
- **Status:** [ ] Not started  

---

### Task P2-11 — Phase 2 QA sign-off (paper trading)

- **Agent:** QA Engineer  
- **Deliverable:**  
  - `docs/qa/phase2_signoff.md` — date, commit SHA, test commands, evidence of **paper** mode, checklist vs `docs/paper_trading.md`  
  - Record of **no live capital** used in validation runs  
  - Regression suite green (unit + integration)  
- **Depends on:** P2-05 backtest acceptance by Quant; P2-08; P2-07 security review closed; P2-10 as applicable  
- **Security review required:** no (QA process) — **yes** if QA touches real broker credentials (prefer Director-owned sandbox only)  
- **Status:** [ ] Not started  

---

## Parallel tracks

| Track | Tasks | When safe to parallelize |
|--------|--------|---------------------------|
| **A — Adapter** | P2-01 → P2-02 | Sequential within track. |
| **B — Strategy / quant** | P2-04 → P2-05 → P2-06 | P2-04 can start once market-data fields are agreed; P2-05 needs P2-04; P2-06 needs spec + harness. |
| **C — Pipeline** | P2-03 | After stream contract known; can use stub stream until P2-02 done. |
| **D — Paper + integration** | P2-07 → P2-08 → P2-09 → P2-10 → P2-11 | P2-07 early dependency on order path (P2-01). |

**Practical parallelism:**  
- **P2-04 (∥) P2-01** after a short **data contract** sync (Quote/bar fields, symbols).  
- **P2-05 (∥) P2-02 / P2-03** once P2-04 v0 spec exists (even if refined later).  
- **P2-09 (∥) P2-08** for spec writing; implementation lands after order routing exists.  

---

## Phase 2 exit criteria

- [ ] **Full adapter:** All `BrokerAdapter` methods implemented for TradeStation with tests; streaming stable under reconnect scenarios per `docs/tradestation_streaming.md`.  
- [ ] **Pipeline:** Real-time data flows through the documented pipeline to strategy consumers with **tenant-scoped** behavior verified by tests.  
- [ ] **Strategy:** Platform Strategy V1 specified, backtested per `docs/backtest_methodology.md`, implemented, and registered as **platform-owned**.  
- [ ] **Paper only:** `TRADING_MODE=paper` (or equivalent) enforced; Security Architect review **closed** for P2-07; runbook followed for paper account verification.  
- [ ] **Risk:** Pre-trade limits active for paper session; documented in `docs/risk_limits_phase2.md`.  
- [ ] **QA:** `docs/qa/phase2_signoff.md` complete; **2026-04-15** Phase 1 sign-off remains valid baseline; Phase 2 sign-off dated when done.  
- [ ] **No live capital** in Phase 2 validation unless Director explicitly approves in writing (Orchestrator escalation path).  

---

*Maintained by: Director + Orchestrator. Created: Phase 2 planning.*

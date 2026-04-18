# Phase 2 — Track A test execution record

**Date:** 2026-04-15  
**Environment:** Windows, Python 3.11.9 (project `.venv`), pytest 8.2.0  
**Commit SHA:** `9f964baf2cf40f731a8667885c2b131a24722ddd`

---

## STEP 1 — Test suites

### `pytest tests/unit/brokers/ -v`

**Result: PASS — 19 passed, 0 failed** (0.73s)

### `pytest tests/integration/ -v`

**Result: PASS — 4 passed, 0 failed** (2.07s)

**Warnings (non-failing):** Starlette `multipart` PendingDeprecationWarning (1×).

### `pytest tests/unit/data/ -v`

**Result: PASS — 2 passed, 0 failed** (0.93s)

**Warnings:** Same Starlette `multipart` PendingDeprecationWarning (1×).

---

## STEP 2 — Paper mode enforcement (targeted)

### `pytest tests/unit/brokers/test_tradestation_auth.py::test_live_url_rejected_in_paper_mode -v`

**Result: PASS — 1 passed, 0 failed** (0.57s)

---

## STEP 3 — Security sign-off (P2-01)

**File:** `docs/security_review_p2_01.md`  
**Status:** **Signed** — Security Architect, Phase 2 Track A approved — 2026-04-15 (all checklist items MET).

---

## STEP 4 — Data layer tenant scoping (manual QA review)

Reviewed `src/data/pipeline.py`, `src/data/store.py`, and `src/tenancy/redis_keys.py`:

| Area | Finding |
|------|---------|
| **Redis publish** | `MarketDataPipeline` publishes only to `bars_channel(self._tenant_id, symbol, interval)` → channel name **starts with `tenant_id`**. |
| **TimescaleDB / SQL writes** | `HistoricalDataStore.upsert_bar` and `fetch_bars` filter and set **`MarketBar.tenant_id`** (and `trading_mode`) on every path; bar tenant must match caller `tenant_id`. |

**Verdict:** No Redis publish or DB write path found in `src/data/` that omits `tenant_id` in the channel key or row/column scope.

---

## STEP 6 — Overall verdict

**PASS** — All tests above passed; P2-01 security review signed; no `tenant_id` gaps identified in `src/data/` for Redis publish or bar persistence.

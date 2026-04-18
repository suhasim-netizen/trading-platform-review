# Phase 1 — Infrastructure

**Goal:** Broker-agnostic execution port (`BrokerAdapter`), multi-tenant data boundaries (`tenant_id`), TS OAuth confined to `src/brokers/tradestation/`, security baseline, initial persistence, and QA gate before any live routing.

**How to use this doc:** Check boxes as each deliverable is verified in the repo. If a prior session already created files, mark the task **complete only after** you confirm every listed file matches the intended contract (not merely “file exists”).

---

## Prerequisites (Director / repo)

- [x] Git repository created and connected to GitHub
- [x] Python virtual environment configured (`requirements.txt` / lockfile as you prefer)
- [x] Ten specialist agent prompts defined (operating model)
- [ ] **Optional verification pass:** Confirm `src/brokers/base.py` (and related broker files) match the Phase 1 contract below before locking downstream work

---

## Phase 1 — Infrastructure (ordered by dependency)

### Task 1 — BrokerAdapter interface and platform models

- **Agent:** App Architect  
- **Deliverable:**  
  - `src/brokers/base.py` — abstract `BrokerAdapter` (authenticate, refresh_token, quotes, account, orders, positions, streaming hooks; all scoped with `tenant_id` where applicable)  
  - `src/brokers/models.py` — platform-native types (`BrokerCredentials`, `AuthToken`, `Order`, `Quote`, `Position`, `Account`, receipts/updates, enums)  
  - `src/brokers/exceptions.py` — broker-agnostic errors (auth, token expiry, network, rate limit, validation)  
  - `docs/broker_adapter_spec.md` — written contract: semantics, errors, extension pattern for new brokers  
- **Depends on:** Nothing (repository exists)  
- **Status:** [ ] Not started  

#### Prompt for App Architect (copy into agent)

```text
You are the App Architect for our autonomous trading platform (stocks & futures).

Architecture rules (non-negotiable):
1) All broker access is through the BrokerAdapter abstraction — no vendor SDK types or vendor-specific enums in shared code.
2) Multi-tenancy: any account, order, position, credential, or stream must be scoped by tenant_id at the API boundary and in persistence-oriented models.
3) TS may appear only in docs that describe the concrete adapter package path; the interface and shared models must stay broker-agnostic.

Task: Phase 1 — Task 1 — BrokerAdapter interface and platform models.

If src/brokers/base.py, models.py, or exceptions.py already exist, treat this as a verification + completion pass: align them to the contract below, fix gaps, and add the missing written spec. Do not rename public methods without noting breaking changes.

Deliverables (exact):
- src/brokers/base.py — ABC BrokerAdapter with async methods: authenticate(credentials), refresh_token(token), get_quote(symbol, tenant_id), get_account(account_id, tenant_id), place_order(order, tenant_id), cancel_order(order_id, tenant_id), get_positions(account_id, tenant_id). Streaming: stream_quotes(symbols, tenant_id) and stream_order_updates(account_id, tenant_id) return AsyncIterator of platform types (implementations may use async generators).
- src/brokers/models.py — Pydantic (v2) or dataclasses for: BrokerCredentials (includes tenant_id; optional OAuth fields via extra allowed), AuthToken, Quote, Account, Order (+ side/type/TIF enums), OrderReceipt, CancelReceipt, Position, OrderUpdate. No broker-specific field names in required fields.
- src/brokers/exceptions.py — BrokerError hierarchy: auth, token expired, network, rate limit, validation.
- docs/broker_adapter_spec.md — For each method: purpose, inputs/outputs, error types, idempotency notes where relevant, how adapters must scope tenant_id, and how to add a second broker without touching core logic.

Constraints:
- Do not add TS imports or URLs outside what is necessary in documentation examples; prefer neutral wording in the spec.
- Keep dependencies minimal; match existing project style and imports (check pytest.ini / pythonpath for src).

Finish by listing files changed and any follow-ups for Tech Lead or Security Architect.
```

---

### Task 2 — Security baseline (env contract, secrets plan, P1-03 gate)

- **Agent:** Security Architect  
- **Deliverable:**  
  - `.env.example` — documented template (broker OAuth placeholders, `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `ENVIRONMENT`, `LOG_LEVEL`, `ALLOWED_TENANT_IDS`, etc.)  
  - `.gitignore` — includes `.env` (verify, do not assume)  
  - `docs/secrets_management.md` — local / CI / prod secret flow, rotation, “never store” rules, encryption-at-rest expectations  
  - `docs/security_review_p1_03.md` — checklist + sign-off line for TS auth implementation (P1-03)
  - `src/config.py` — `Settings` (e.g. Pydantic `BaseSettings`) matching the env contract; no secrets hardcoded  
- **Depends on:** Task 1 (credential/token *shapes* in `BrokerCredentials` / `AuthToken`)  
- **Status:** [ ] Not started  

#### Prompt for Security Architect (copy into agent)

```text
You are the Security Architect for our multi-tenant trading platform.

Task: Phase 1 — Task 2 — Security baseline (environment contract, secrets management plan, and formal gate for broker OAuth implementation).

Read src/brokers/models.py (BrokerCredentials, AuthToken) so the env contract matches how Tech Lead will load OAuth client settings vs per-tenant secrets stored encrypted in the database.

Deliverables (exact):
- .env.example — Fully commented template: BROKER_CLIENT_ID, BROKER_CLIENT_SECRET, BROKER_REDIRECT_URI, BROKER_AUTH_BASE_URL, BROKER_API_BASE_URL, BROKER_WS_BASE_URL, DATABASE_URL, SECRET_KEY (app signing / session material), TOKEN_ENCRYPTION_KEY (Fernet or documented format), ENVIRONMENT, LOG_LEVEL, ALLOWED_TENANT_IDS (comma-separated; include director for Phase 1). No real values.
- Verify .gitignore excludes .env; if not, fix it.
- docs/secrets_management.md — Local dev (.env), CI (injected vars), production (recommend AWS Secrets Manager, Vault, or Azure Key Vault) with migration path from flat env; rotation policy; explicit NEVER list (no plaintext broker tokens in logs, DB, or error payloads); encryption-at-rest expectations for broker_credentials rows.
- docs/security_review_p1_03.md — Checklist Tech Lead must satisfy before OAuth code is considered approved: TLS-only, no token logging, tenant-scoped token storage, typed errors, no secrets in code, redirect URI match, mock-based tests in CI, etc. Include a physical sign-off line for you (Security Architect) and date.
- src/config.py — Pydantic Settings (pydantic-settings) loading from environment / .env; validate lengths and allowed ENVIRONMENT values; expose helper like allowed_tenants() if appropriate. No default secrets that look like production-ready keys.

Rules:
- You may adjust field names only if you update .env.example and coordinate in a short note at the bottom of secrets_management.md.
- Do not implement the TS OAuth flow here — that is Task 7 — but your checklist is the hard gate before merge.

Finish with: (1) confirmation .env is gitignored, (2) any risks you want Data Engineer to handle in Task 5.
```

---

### Task 3 — Project scaffolding and module boundaries

- **Agent:** Tech Lead  
- **Deliverable:**  
  - Importable `src/` package tree enforcing: **no broker vendor names** outside `src/brokers/tradestation/`  
  - API entrypoint stub (e.g. `src/api/main.py`) and **tenant context** at the boundary (e.g. middleware or equivalent under `src/api/` or `src/tenancy/`)  
  - Stubs for core services you plan in Phase 1 (engine / OMS / registry / onboarding — align names to your chosen layout) with `pass` or explicit `NotImplementedError` outside current scope  
  - `src/brokers/tradestation/` — **stub** `adapter.py` / auth helper module(s) only until Task 7 (no full OAuth until Task 2 sign-off)  
  - `tests/` layout (`unit/`, `integration/`, `fixtures/`) + `pytest.ini` or `pyproject.toml` `pythonpath` so `src` imports resolve  
  - `docs/folder_structure.md` — rationale per top-level area; maps to the three architecture rules (adapter-only, tenant scope, strategy registry ownership)  
- **Depends on:** Task 1 (stable module names for `brokers` and shared types)  
- **Status:** [ ] Not started  

#### Prompt for Tech Lead (copy into agent)

```text
You are the Tech Lead for our multi-tenant trading platform.

Architecture rules:
1) BrokerAdapter is the only public broker port for core logic; concrete brokers live under src/brokers/<vendor>/.
2) The string "TS" (and vendor URLs) must appear only inside src/brokers/tradestation/.
3) Every HTTP request that touches tenant data must have a validated tenant_id on the request context (middleware or equivalent) before routers call services.

Task: Phase 1 — Task 3 — Project scaffolding and module boundaries.

If a scaffold already exists, normalize it to the deliverables below without breaking imports/tests; prefer small focused commits.

Deliverables:
- Importable src/ tree with __init__.py as needed.
- src/api/main.py — FastAPI app factory; include health route; wire middleware for tenant context if that lives in api layer (or document delegation to src/tenancy/).
- Tenant context: implement or stub src/tenancy/middleware.py (or src/api/middleware/tenant_context.py) that reads tenant_id from header (e.g. X-Tenant-ID) or agreed mechanism, validates against Settings.ALLOWED_TENANT_IDS when in production mode, and stores context for downstream code.
- Stubs: OMS/service, onboarding service, strategy executor/registry hooks as appropriate for this repo — use pass or NotImplementedError with one-line docstring referencing future phase.
- src/brokers/tradestation/ — adapter.py and auth.py stubs only: class skeleton implementing BrokerAdapter with NotImplementedError on all methods until Task 7 (or inherit partial if Task 7 file already exists — do not implement OAuth here without Security sign-off).
- tests/ layout with unit/ and integration/; pytest.ini (or pyproject.toml) pythonpath includes src; tests collect without errors.
- docs/folder_structure.md — Each top-level package: purpose + how it enforces broker abstraction, tenant isolation, and strategy ownership boundaries.

Out of scope for this task: full OAuth (Task 7), full Alembic migration content beyond a placeholder if already present (Task 5), Quant/strategy logic.

Verify: pytest passes or, if no tests yet, python -c imports for the FastAPI app succeed.

Report files created/modified and any TODOs blocking Task 4 or Task 6.
```

---

### Task 4 — Database schema design (logical model and tenant isolation)

- **Agent:** App Architect (with Data Engineer as reviewer for feasibility)  
- **Deliverable:**  
  - `docs/database_schema.md` — entities, relationships, **row-level `tenant_id` / FK to `tenants`** on all tenant-owned tables, indexing notes, ERD description  
  - Tables to cover at minimum: `tenants`, `broker_credentials` (encrypted payload + metadata only), `accounts`, `orders`, `positions`, `strategies` (owner field for platform vs tenant), `strategy_allocations`  
- **Depends on:** Task 1 (domain shapes), Task 3 (where `db/` and ORM modules live)  
- **Status:** [ ] Not started  

#### Prompt for App Architect (+ Data Engineer review) (copy into agent)

```text
You are the App Architect for our multi-tenant trading platform. Coordinate with the Data Engineer for feasibility (indexes, UUID vs string PKs, async SQLAlchemy); they implement ORM in Task 5 — your output here is the authoritative logical design.

Task: Phase 1 — Task 4 — Database schema design (logical model + tenant isolation).

Context: Row-level multi-tenancy for Phase 1 (single schema): every tenant-owned row carries tenant_id (FK to tenants) and queries must filter by tenant_id. Director-owned strategies use an owner field; future client strategies remain private per tenant.

Deliverable (exact):
- docs/database_schema.md — Sections: (1) isolation pattern and threat model (what row-level scoping prevents), (2) table list with columns and types (conceptual), (3) relationships diagram described in prose or ASCII ERD, (4) indexes (tenant_id on all large tenant-scoped tables), (5) broker_credentials: store ciphertext + metadata only — no plaintext refresh tokens, (6) migration notes for Data Engineer.

Minimum tables: tenants; broker_credentials; accounts; orders; positions; strategies (owner: platform | tenant); strategy_allocations (capital per tenant per strategy).

Map fields to domain concepts from src/brokers/models.py where applicable (orders, positions) but DB IDs may be UUIDs — state that explicitly.

Explicit non-goals: schema-per-tenant in Phase 1 unless you document a strong reason.

Handoff: End the doc with a "Data Engineer checklist" bullet list they must satisfy in Task 5 (Alembic revision, indexes, tests).
```

---

### Task 5 — ORM models, Alembic migration, tenant scoping helpers

- **Agent:** Data Engineer  
- **Deliverable:**  
  - `src/db/base.py` — declarative `Base`  
  - `src/db/session.py` — async (or sync, but be consistent) session factory + pool settings  
  - `src/db/models.py` or `src/db/models/*.py` — SQLAlchemy models matching Task 4  
  - `src/db/migrations/` — Alembic env + initial revision (e.g. `versions/001_initial_schema.py`)  
  - Tenant guardrails (mixin, query helper, or documented pattern) to prevent accidental cross-tenant reads  
  - `tests/unit/db/test_tenant_scoping.py` (or equivalent) — isolation tests  
  - `src/tenants/models.py` or equivalent — Pydantic/DTO layer aligned with DB (if used by API)  
- **Depends on:** Task 4, Task 3  
- **Status:** [ ] Not started  

#### Prompt for Data Engineer (copy into agent)

```text
You are the Data Engineer for our multi-tenant trading platform.

Task: Phase 1 — Task 5 — ORM models, Alembic migration, tenant scoping helpers.

Inputs: docs/database_schema.md (Task 4) is source of truth. src/db/ layout from Task 3. Use SQLAlchemy 2.x style consistent with the repo. Prefer async session if the rest of the stack is async (DATABASE_URL may use asyncpg).

Deliverables (exact):
- src/db/base.py — DeclarativeBase.
- src/db/session.py — engine + sessionmaker / async_sessionmaker, pool settings appropriate for dev and prod notes in docstring.
- ORM models in src/db/models.py or src/db/models/ package matching the schema doc: tenants, broker_credentials, accounts, orders, positions, strategies, strategy_allocations. Every tenant-owned table: non-null tenant_id FK; indexes on tenant_id.
- Alembic: alembic.ini at repo root or documented location; env.py loads Base metadata; initial revision creating all tables; README snippet: how to run upgrade head.
- Tenant guardrails: mixin or query helper documented in docs/database_schema.md "Implementation notes" OR short docs/db/tenant_scoping.md — pattern that makes accidental cross-tenant SELECTs harder (e.g. required tenant filter helper).
- tests/unit/db/test_tenant_scoping.py — Create two tenants in test DB (or in-memory SQLite if compatible); prove a query filtered by tenant A never returns tenant B rows. Use transactions/fixtures per project conventions (see tests/conftest.py).
- DTO layer: src/tenants/models.py (or agreed path) — Pydantic models for API use aligned with DB.

Constraints:
- No plaintext broker tokens in columns — store encrypted blob + key id/version if designed that way; align with Security docs Task 2.
- Do not leak raw connection strings in logs.

Finish with migration command verification and any follow-ups for Tech Lead Task 7 (token persistence API).
```

---

### Task 6 — Broker registry and factory (no vendor leakage)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/brokers/registry.py` and factory/wiring (e.g. `src/services/broker_factory.py`) — resolve a `BrokerAdapter` implementation by config; **call sites use only** `BrokerAdapter` types  
  - Unit tests: registry/factory behavior mocked; no live broker  
- **Depends on:** Task 1, Task 3, Task 2 (`Settings` for broker selection / URLs)  
- **Status:** [ ] Not started  

#### Prompt for Tech Lead (copy into agent)

```text
You are the Tech Lead for our multi-tenant trading platform.

Task: Phase 1 — Task 6 — Broker registry and factory (no vendor leakage).

Architecture rules:
- Application code outside src/brokers/tradestation/ must depend on BrokerAdapter (type hints) and factory/registry — never import TSAdapter directly except in the composition root or broker package __init__ if needed for registration.
- Selection of which adapter to use must come from Settings (e.g. BROKER_IMPL=tradestation) or a small allowed map.

Deliverables:
- src/brokers/registry.py — Register concrete adapter classes by string key; thread-safe enough for tests; clear error for unknown broker key.
- src/services/broker_factory.py (or agreed path) — build_broker_adapter(settings) -> BrokerAdapter; only this module (or registry) imports TSAdapter from tradestation package.
- Unit tests: tests/unit/brokers/test_registry.py (or extend existing) — unknown key raises; known key returns instance (use mock/fake adapter if needed to avoid live calls).
- Ensure grep of "TS" outside src/brokers/tradestation/ returns zero matches in Python sources (tests may use string "tradestation" as config key — lowercase config is OK).

Out of scope: implementing OAuth (Task 7); implementing full adapter methods beyond what exists for tests.

Document in docs/folder_structure.md addendum or short docs/broker_factory.md how a second broker would register.

Report any circular import issues fixed.
```

---

### Task 7 — TS OAuth (authenticate + refresh only for Phase 1)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/brokers/tradestation/auth.py` — authorization-code exchange, refresh, typed errors  
  - `src/brokers/tradestation/adapter.py` — `TSAdapter` implements `authenticate` + `refresh_token`; **other** `BrokerAdapter` methods explicitly stubbed until later phases
  - Token handling: never log tokens; persist only via encrypted path aligned with Task 5 + Task 2  
  - `docs/tradestation_auth_flow.md` — sequence diagram or step list + token lifecycle  
  - `tests/unit/brokers/test_tradestation_auth.py` — mocked HTTP only  
- **Depends on:** Task 1, Task 2 (**Security Architect sign-off** on `docs/security_review_p1_03.md`), Task 3, Task 5 (if persisting tokens in DB in Phase 1)  
- **Status:** [ ] Not started  

#### Prompt for Tech Lead (copy into agent)

```text
You are the Tech Lead for our multi-tenant trading platform.

Task: Phase 1 — Task 7 — TS OAuth (authenticate + refresh_token only).

Hard prerequisites (verify before coding):
- docs/security_review_p1_03.md must be reviewed and signed by Security Architect (Director confirms). If not signed, stop and report.
- src/config.py provides broker OAuth-related settings from env.
- BrokerAdapter contract in src/brokers/base.py is stable.

Scope:
- Implement OAuth2 authorization code exchange and refresh in src/brokers/tradestation/auth.py using httpx (async). Map HTTP failures to src/brokers/exceptions.py types — no raw response bodies in exception messages surfaced to API layer.
- src/brokers/tradestation/adapter.py — TSAdapter implements authenticate(BrokerCredentials) and refresh_token(AuthToken) fully; all other BrokerAdapter methods remain stubs raising NotImplementedError or explicit "Phase 2" message.
- tenant_id: AuthToken and any persistence hooks must carry tenant_id; if persisting, use Data Engineer models + encryption helper from src/security/crypto.py (or equivalent) — never write plaintext tokens to DB or logs.
- Logging: log event types only (token_refreshed, auth_failed) — never log access_token, refresh_token, client_secret.

Deliverables:
- docs/tradestation_auth_flow.md — Step-by-step OAuth sequence, token lifetimes, error handling, diagram in ASCII or Mermaid.
- tests/unit/brokers/test_tradestation_auth.py — Mock httpx responses; cover success, 401, network error, malformed JSON.

Constraints:
- All TS-specific URLs, paths, headers, and JSON field names stay inside src/brokers/tradestation/.
- Register adapter in registry/factory from Task 6 if not already.

Finish with manual test checklist for Director (what to put in .env, what URL to hit) without exposing secrets.
```

---

### Task 8 — Strategy registry stub (ownership tags, no client IP sharing)

- **Agent:** Tech Lead  
- **Deliverable:**  
  - `src/strategies/registry.py` — register/list by **owner** (platform / `tenant_id`); structure supports future tenant-private strategies  
  - `src/strategies/base.py` (or equivalent) — abstract strategy interface stub  
  - Tests or docstring contract stating **no cross-tenant strategy payload access**  
- **Depends on:** Task 3  
- **Status:** [ ] Not started  

#### Prompt for Tech Lead (copy into agent)

```text
You are the Tech Lead for our multi-tenant trading platform.

Task: Phase 1 — Task 8 — Strategy registry stub (ownership tags; no cross-tenant IP).

Context: In Phase 1 the Director owns all strategies; clients only allocate capital. The registry must still model owner = platform vs tenant for future client strategies and must never return another tenant's strategy parameters or code.

Deliverables:
- src/strategies/base.py — Abstract base class for strategies: minimal interface (e.g. name, owner_id, tenant_id optional for platform-global) — enough for Phase 2 quant work to extend.
- src/strategies/registry.py — In-memory registry acceptable for Phase 1: register(strategy_meta), list(owner_filter), get(id) with tenant guard: if strategy is tenant-owned, caller must supply matching tenant_id or raise/forbid.
- tests/unit/strategies/test_registry_tenant_guard.py (or extend existing strategy tests) — prove tenant A cannot read tenant B's registered strategy payload.
- Document in module docstring: "Client strategy IP is private; no cross-tenant reads."

Out of scope: real execution engine, broker calls, Quant Analyst specs.

Keep aligned with ADR docs in docs/adr/ if present; update ADR only if Director asks.

Report public API for Portfolio Manager / executor for Phase 2.
```

---

### Task 9 — QA Phase 1 validation and sign-off

- **Agent:** QA Engineer  
- **Deliverable:**  
  - Test evidence: `pytest` green for unit + critical integration (tenant isolation, broker contract smoke)  
  - Written sign-off note (e.g. `docs/qa/phase1_signoff.md` or comment in PR) — explicitly states P1-03 auth and P1-05 secrets compliance verified  
  - No live capital / production orders in Phase 1 scope unless Director explicitly escalates  
- **Depends on:** Tasks 2, 5, 7 (and stable CI or local reproducible commands documented in `README.md`)  
- **Status:** [ ] Not started  

#### Prompt for QA Engineer (copy into agent)

```text
You are the QA Engineer for our multi-tenant trading platform.

Task: Phase 1 — Task 9 — Validation and formal Phase 1 sign-off.

Objectives:
- Prove the architecture rules hold in code and tests: BrokerAdapter-only outside tradestation package; tenant isolation in middleware + DB tests; no secrets in logs in auth tests (static review of logging calls acceptable).
- Ensure pytest passes locally with documented commands.

Steps:
1) Run full test suite (unit + integration); capture command and result summary.
2) Static checks: ripgrep or equivalent — confirm no accidental "TS" imports outside src/brokers/tradestation/ (allow lowercase config key "tradestation").
3) Review docs/security_review_p1_03.md — confirm each item addressed or explicitly waived by Director; if auth merged before sign-off, flag as defect to Director.
4) Review .env.example vs src/config.py for parity.
5) Smoke test FastAPI app starts (uvicorn) with test Settings or documented .env — no live broker calls required; use mocks.

Deliverables:
- docs/qa/phase1_signoff.md — Date, commit SHA, test command, pass/fail, checklist of verified items, explicit statement: "P1-03 auth and P1-05 secrets compliance verified" or list of blocking gaps.
- If failures: file concise bug list with owner (Tech Lead / Security / Data) per item.

Constraints:
- Do not use real production credentials or place real orders.
- No load testing or production deployment in Phase 1 sign-off unless Director explicitly requests.

Escalate to Director only for security/compliance uncertainties or cross-agent disputes per Orchestrator policy.
```

---

## Phase 1 exit criteria (all must be true)

- [ ] `BrokerAdapter` + models documented and frozen for Phase 2 unless ADR amended  
- [ ] Scaffold importable; tenant boundary enforced at API/middleware  
- [ ] Security baseline committed; P1-03 checklist **signed** before auth was merged (or re-verify if auth predates sign-off)  
- [ ] Initial migration applies cleanly; tenant scoping tests pass  
- [ ] TS auth implemented **only** under `src/brokers/tradestation/`; rest of codebase uses `BrokerAdapter` only
- [ ] QA Phase 1 sign-off recorded  

---

## After Phase 1 (do not start before exit criteria)

- **Quant Analyst** — first strategy specification (Director-owned strategies in early phases)  
- **Portfolio Manager** — live strategy status (only after QA + Director risk approval)  

---

*Maintained by: Director + Orchestrator. Last updated: 2026-04-12 (agent prompts added).*

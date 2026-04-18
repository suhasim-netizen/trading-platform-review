# Database schema (Phase 1) — logical model + tenant isolation

This document is the **authoritative logical database design** for Phase 1. It assumes a **single shared schema** with **row-level multi-tenancy** and is designed to be feasible for the Data Engineer to implement with SQLAlchemy (+ Alembic) in Task 5.

**Explicit non-goal (Phase 1):** schema-per-tenant. The operational and migration overhead is not justified for Phase 1; we revisit only for regulated tenants or hard isolation requirements.

---

## 1) Isolation pattern and threat model

### Isolation pattern (row-level scoping)

- **Every tenant-owned row includes `tenant_id`** (FK → `tenants.tenant_id`) and **every query includes a `tenant_id` filter**.
- Where we maintain **paper vs live isolation**, rows also include `trading_mode` (e.g. `"paper"` / `"live"`) and queries filter by both `(tenant_id, trading_mode)`.
- For PostgreSQL deployments, enable **Row Level Security (RLS)** on tenant-owned tables and enforce:

  - Policy: `tenant_id = current_setting('app.tenant_id')`
  - App sets `SET LOCAL app.tenant_id = '<tenant_id>'` per request/session

This yields defense-in-depth: **application-layer filters** + **database-enforced RLS**.

### Threat model: what row-level scoping prevents

Row-level scoping is designed to prevent:

- **Accidental data leakage** (developer forgets a filter; RLS blocks access).
- **ID-guessing / enumeration attacks** (tenant B cannot fetch tenant A’s rows by UUID).
- **Cross-tenant execution mistakes** (an order record or broker credential for tenant A cannot be read/used when processing tenant B jobs, if code consistently keys by `tenant_id` and RLS is enabled).

Row-level scoping does **not** fully prevent:

- **Application bugs that intentionally bypass RLS** (e.g. connecting with a superuser role, disabling RLS, or using a shared “admin” session without `app.tenant_id` set).
- **Side-channel leaks** (timing, counts, error messages) unless endpoints return “not found” for unauthorized resources and avoid cross-tenant aggregates.

Operational controls required:

- A dedicated DB role for the app with **no RLS bypass**.
- CI tests that assert **cross-tenant reads fail** for sensitive endpoints and repositories.

---

## 2) Table list (columns and conceptual types)

Types are conceptual; Data Engineer may map to SQLAlchemy types. **Primary keys are UUIDs** (stored as `UUID` in Postgres; acceptable as `CHAR(36)` / `String(36)` in SQLite/dev). We keep `tenant_id` as a stable **string slug** for Phase 1 (e.g. `"director"`, `"tenant_a"`) to align with JWT claims and config.

### `tenants`

- **`tenant_id`**: `string` (PK) — stable tenant identifier used everywhere
- `display_name`: `string`
- `status`: `enum` (`pending` | `active` | `suspended`)
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`

### `broker_credentials` (tenant-scoped, per broker + trading mode)

**Purpose:** store **ciphertext + metadata only**; never plaintext secrets.

- **`id`**: `uuid` (PK)
- **`tenant_id`**: `string` (FK → `tenants.tenant_id`, indexed)
- **`trading_mode`**: `string` (`paper` | `live`, indexed)
- **`broker_name`**: `string` (e.g. `"tradestation"` logically; do not bake vendor fields into shared schema)
- `api_base_url`: `string`
- `ws_base_url`: `string`
- `token_url`: `string?`
- `client_id`: `string?`
- **`client_secret_ciphertext`**: `text?`
- **`access_token_ciphertext`**: `text?`
- **`refresh_token_ciphertext`**: `text?`
- `token_expires_at`: `timestamptz?`
- `scopes`: `string?` (optional, broker-agnostic free text)
- `account_id_default`: `string?` (optional convenience)
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`

**Constraints**

- Unique: `(tenant_id, trading_mode)` or `(tenant_id, trading_mode, broker_name)` depending on whether we allow multiple brokers per tenant+mode in Phase 1. Recommendation: **unique `(tenant_id, trading_mode)`** for Phase 1 simplicity.

### `accounts` (tenant-scoped)

Represents brokerage accounts available to a tenant (usually remote broker accounts).

- **`id`**: `uuid` (PK)
- **`tenant_id`**: `string` (FK → `tenants.tenant_id`, indexed)
- **`trading_mode`**: `string` (`paper` | `live`, indexed)
- **`broker_account_id`**: `string` (opaque remote account id, indexed)
- `name`: `string?`
- `currency`: `string` (default `"USD"`)
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`

**Constraints**

- Unique: `(tenant_id, trading_mode, broker_account_id)`

### `orders` (tenant-scoped)

Maps to `src/brokers/models.py::Order` + `OrderReceipt` / `OrderUpdate`:

- **`id`**: `uuid` (PK) — internal order id
- **`tenant_id`**: `string` (FK, indexed)
- **`trading_mode`**: `string` (indexed)
- **`account_id`**: `uuid` (FK → `accounts.id`, indexed)
- `client_order_id`: `string?` (idempotency token if caller provides one; unique per account recommended)
- `broker_order_id`: `string?` (opaque broker id, indexed)
- `symbol`: `string`
- `side`: `string` (from `OrderSide`: `buy`/`sell`)
- `quantity`: `numeric(24,8)`
- `order_type`: `string` (from `OrderType`)
- `time_in_force`: `string` (from `TimeInForce`)
- `limit_price`: `numeric(24,8)?`
- `stop_price`: `numeric(24,8)?`
- `status`: `string` (from `OrderStatus`)
- `submitted_at`: `timestamptz?`
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`
- `raw`: `json?` (optional broker response snapshot; **must remain tenant-scoped**)

**Constraints**

- Unique (recommended): `(tenant_id, trading_mode, account_id, client_order_id)` where `client_order_id IS NOT NULL`

### `positions` (tenant-scoped)

Maps to `src/brokers/models.py::Position`:

- **`id`**: `uuid` (PK)
- **`tenant_id`**: `string` (FK, indexed)
- **`trading_mode`**: `string` (indexed)
- **`account_id`**: `uuid` (FK → `accounts.id`, indexed)
- `symbol`: `string` (indexed)
- `quantity`: `numeric(24,8)`
- `avg_cost`: `numeric(24,8)?`
- `market_value`: `numeric(24,8)?`
- `updated_at`: `timestamptz`
- `raw`: `json?`

**Constraints**

- Unique: `(tenant_id, trading_mode, account_id, symbol)`

### `strategies`

Phase 1 strategy registry is logical and supports ownership:

- **`id`**: `uuid` (PK)
- `owner_kind`: `enum` (`platform` | `tenant`)
- `owner_tenant_id`: `string?` (FK → `tenants.tenant_id`; null iff `owner_kind='platform'`, indexed)
- `name`: `string`
- `code_ref`: `string` (opaque reference to code/artifact; never another tenant’s private path)
- `version`: `string?` (optional; Phase 1 may default to `"1"`)
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`

**Visibility rule (enforced in queries):**

- Tenant can view:
  - all `owner_kind='platform'` strategies they are entitled to (if entitlement table exists), and
  - their own where `owner_kind='tenant' AND owner_tenant_id = <tenant_id>`

### `strategy_allocations` (tenant-scoped)

Defines how much capital a tenant allocates to a strategy (by trading mode and optionally account).

- **`id`**: `uuid` (PK)
- **`tenant_id`**: `string` (FK, indexed)
- **`trading_mode`**: `string` (indexed)
- **`strategy_id`**: `uuid` (FK → `strategies.id`, indexed)
- `account_id`: `uuid?` (FK → `accounts.id`, indexed) — null means “tenant-wide allocation”
- `allocation_amount`: `numeric(24,8)` (base currency amount)
- `allocation_currency`: `string` (default `"USD"`)
- `risk_limits_ref`: `string?` (optional pointer to a risk config snapshot)
- `created_at`: `timestamptz`
- `updated_at`: `timestamptz`

**Constraints**

- Unique (recommended): `(tenant_id, trading_mode, strategy_id, account_id)` (treat null as a separate scope)

---

## 3) Relationships diagram (ASCII ERD)

```
tenants (tenant_id PK)
   |
   +--< broker_credentials (tenant_id FK, trading_mode, broker_name, ciphertext...)
   |
   +--< accounts (tenant_id FK, trading_mode, broker_account_id)
   |        |
   |        +--< orders (tenant_id FK, trading_mode, account_id FK)
   |        |
   |        +--< positions (tenant_id FK, trading_mode, account_id FK)
   |
   +--< strategies (owner_kind='tenant' => owner_tenant_id FK)
   |
   +--< strategy_allocations (tenant_id FK, strategy_id FK, account_id FK?)
```

Key rule: **every child table includes `tenant_id` even when it has an `account_id` FK**. This prevents cross-tenant joins from accidentally succeeding if an `account_id` is guessed.

---

## 4) Indexes (Phase 1 minimum)

General rule: on all large tenant-scoped tables, index `tenant_id` (and `trading_mode` where present). Recommended composite indexes:

- `broker_credentials`
  - `INDEX (tenant_id, trading_mode)`
  - `UNIQUE (tenant_id, trading_mode)` (or include `broker_name`)

- `accounts`
  - `INDEX (tenant_id, trading_mode)`
  - `UNIQUE (tenant_id, trading_mode, broker_account_id)`

- `orders`
  - `INDEX (tenant_id, trading_mode, created_at DESC)`
  - `INDEX (tenant_id, trading_mode, account_id, created_at DESC)`
  - `INDEX (tenant_id, trading_mode, broker_order_id)` (if broker_order_id is used for lookups)
  - Partial unique: `UNIQUE (tenant_id, trading_mode, account_id, client_order_id) WHERE client_order_id IS NOT NULL`

- `positions`
  - `INDEX (tenant_id, trading_mode, account_id)`
  - `UNIQUE (tenant_id, trading_mode, account_id, symbol)`

- `strategies`
  - `INDEX (owner_kind, owner_tenant_id)`
  - Optional: `UNIQUE (owner_kind, owner_tenant_id, name, version)` (or slug/version if later introduced)

- `strategy_allocations`
  - `INDEX (tenant_id, trading_mode)`
  - `INDEX (tenant_id, trading_mode, strategy_id)`
  - `UNIQUE (tenant_id, trading_mode, strategy_id, account_id)`

**Data Engineer feasibility note:** these indexes are compatible with both SQLite (dev/tests) and PostgreSQL; partial unique constraints are PostgreSQL-only (SQLite supports partial indexes in modern versions, but behavior differs). If portability is needed, enforce via application validation + regular unique in Phase 1.

---

## 5) `broker_credentials` storage rules (ciphertext + metadata only)

Non-negotiable:

- **Never store plaintext** `client_secret`, `access_token`, or `refresh_token`.
- Store only:
  - **ciphertext** (e.g. Fernet-encrypted strings) and
  - minimal metadata needed for refresh logic (e.g. `token_expires_at`, optional `scopes`).
- Logs and error messages must not include ciphertext either (treat ciphertext as sensitive).

Recommended crypto posture:

- One platform-level encryption key (Phase 1) is acceptable; future enhancement is per-tenant envelope encryption.
- Rotate keys by introducing `encryption_key_id` and re-wrapping ciphertext in a migration (future task).

---

## 6) Migration notes for Data Engineer (Task 5)

### Primary key decisions (UUID vs string)

- **`tenant_id`**: keep as `string` PK in `tenants` for Phase 1 (stable slug used in JWT and configuration).
- Other entities: use **UUID PKs** (`UUID` in Postgres; `String(36)` for SQLite tests is acceptable).

### SQLAlchemy / async feasibility

Phase 1 code currently uses synchronous SQLAlchemy sessions; Task 5 may implement:

- Either **sync SQLAlchemy** (fastest, consistent with current code), or
- **async SQLAlchemy** (acceptable), but must preserve:
  - the tenant-scoped query helper pattern (`tenant_scoped_query` equivalent),
  - per-request `tenant_id` enforcement, and
  - future RLS session setting when on Postgres.

If choosing async SQLAlchemy:

- Use `create_async_engine` + `AsyncSession`
- Provide a small repository layer that requires `tenant_id` parameters for all methods
- Ensure tests cover cross-tenant leakage prevention

### RLS implementation plan (Postgres)

When targeting Postgres:

- Add Alembic migrations that:
  - enable RLS on tenant-owned tables
  - add policies referencing `current_setting('app.tenant_id')`
- Ensure the app sets `SET LOCAL app.tenant_id` on each transaction (or connection checkout hook).

### Compatibility with current repo model names

The current ORM includes a `tenant_broker_configs` table and basic `orders` / `strategies`. Task 5 should:

- Rename or alias as needed to match this doc’s logical names:
  - `tenant_broker_configs` ≈ `broker_credentials`
- Add missing tables: `tenants`, `accounts`, `positions`, `strategy_allocations`
- Extend `orders` to include required order fields (`order_type`, `time_in_force`, prices, account FK, timestamps) while keeping tenant scoping.

---

## Data Engineer checklist (must satisfy in Task 5)

- **Alembic**: create a new revision implementing tables + constraints from this document.
- **Tenant scoping**: every tenant-owned table contains `tenant_id` (FK to `tenants`) and is indexed.
- **Indexes**: implement composite indexes listed above for `orders`, `positions`, `strategy_allocations`.
- **Ciphertext only**: `broker_credentials` stores only encrypted secrets + metadata; no plaintext tokens or secrets anywhere.
- **Repository/query API**: every query path requires `tenant_id` (and `trading_mode` where applicable); add a helper similar to `tenant_scoped_query`.
- **Tests**:
  - unit tests: query helpers always filter by tenant
  - integration tests: tenant A cannot list/get tenant B orders/strategies (extend existing tests)
- **RLS (Postgres target)**: document or implement migration steps for RLS policies (even if SQLite tests don’t exercise them).


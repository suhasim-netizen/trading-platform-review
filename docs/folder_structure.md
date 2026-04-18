# Folder Structure (Phase 1)

This document explains what each top-level `src/` package is responsible for, and which code paths enforce the three non-negotiable architecture constraints:

1) **Broker abstraction**: core logic calls only the `BrokerAdapter` port.
2) **Tenant isolation**: every HTTP request touching tenant data is validated by middleware and stored in request-scoped context.
3) **Strategy ownership**: strategy access is filtered by tenant ownership rules (platform vs tenant-owned).

## `src/api/`

FastAPI app entrypoints and route definitions.

- Enforces tenant boundary by wiring `src/tenancy/middleware.py` into the app.
- Routes may read tenant-scoped values only via `src/tenancy/context.py` (never infer `tenant_id` from request parameters).
- Deliverable for Task 3: `src/api/main.py` is an app factory with `/health`.

## `src/tenancy/`

Request-scoped tenant context and HTTP-layer validation.

- `src/tenancy/middleware.py` reads `X-Tenant-ID` (and optionally `X-Trading-Mode`) from request headers.
- In production mode, it validates the tenant against `Settings.allowed_tenants()` (derived from `ALLOWED_TENANT_IDS`).
- It stores `tenant_id` and `trading_mode` in contextvars so downstream code can call `get_tenant_id()` / `get_trading_mode()`.

## `src/brokers/`

All broker interaction surfaces live behind adapters.

- `src/brokers/base.py` defines the **public** `BrokerAdapter` port (methods used by core logic).
- `src/brokers/registry.py` provides adapter registration + resolution.
- Concrete broker packages live under `src/brokers/<vendor>/`.
  - Vendor-specific code is allowed only inside `src/brokers/tradestation/`.
  - The rest of the platform imports only `BrokerAdapter` (or resolves adapters via the registry).

## `src/services/`

Composition helpers that connect core services to tenant configuration.

- `services/broker_factory.py` builds the concrete broker adapter from `Settings` (`BROKER_IMPL`) and returns a `BrokerAdapter`.
- Adapter selection is string-key based and resolved through `src/brokers/registry.py`; no vendor imports exist in this package.

## `src/db/`

Persistence and DB model definitions.

- Tenant-scoped persistence must include `tenant_id` columns and filters.
- Any tenant filtering should be done in repository/query helpers to avoid accidental cross-tenant reads.

## `src/oms/`

Order Management System.

- Task 3 deliverable: `oms/service.py` is a stub placeholder.
- Future phases will implement tenant-scoped order listing and placement, routing execution through the tenant’s resolved `BrokerAdapter`.

## `src/strategies/`

Strategy registry + execution framework.

- `strategies/registry.py` is responsible for visibility/ownership rules (platform vs tenant-owned strategies).
- `strategies/executor.py` is responsible for routing execution through the requesting tenant’s broker adapter.
- Task 3 deliverable: these modules are stubbed in Phase 1.

## `src/onboarding/`

Tenant onboarding automation.

- Task 3 deliverable: `onboarding/service.py` is stubbed.
- Future phases will namespace tenant resources, dispatch secrets provisioning hooks, and mark onboarding completion flags.

## `src/security/`

Cryptography and secrets handling helpers.

- Provides at-rest encryption/decryption primitives used by DB-backed secrets storage.
- Core logic should never handle raw secrets outside the adapter/config boundaries.


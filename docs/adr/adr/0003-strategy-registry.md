# ADR 0003: Strategy registry schema and access control

## Status

Accepted

## Context

Strategies are intellectual property: platform-supplied strategies may be shared with subscribing tenants under license, while tenant-authored strategies must never be visible to other tenants. The registry must support versioning, activation per account, and auditability.

## Decision

**Shared tables with ownership metadata and explicit visibility rules.**

### Entities (logical schema)

1. **`strategy_definition`**

   - `id` (UUID)
   - `slug` — unique per owner scope (see below)
   - `version` — monotonic integer or semver string; immutable row per version
   - `owner_kind` — enum: `platform` | `tenant`
   - `owner_tenant_id` — `NULL` when `owner_kind = platform`, else the authoring tenant
   - `name`, `description` (non-sensitive)
   - `artifact_uri` or `spec_json` — reference to stored logic (encrypted at rest if contains sensitive parameters)
   - `created_at`, `created_by`, `deprecated_at` (optional)

   **Uniqueness:** `(owner_kind, owner_tenant_id, slug, version)` unique; for platform, `owner_tenant_id` is NULL and handled with a partial unique index.

2. **`strategy_entitlement`** (what a tenant may run)

   - `tenant_id` — subscriber
   - `strategy_definition_id` — FK
   - `granted_at`, `revoked_at`, `grant_source` (subscription, custom contract)

   Platform strategies: rows link consumer `tenant_id` to platform `strategy_definition_id`. Tenant strategies: only the owning tenant has entitlements (or internal admin tooling).

3. **`strategy_binding`** (optional, execution scope)

   - Links `strategy_definition_id` + `tenant_id` + `broker_account_id` + risk limits snapshot id.

### Access control rules

- **List / get definition:** Caller supplies `tenant_id` from auth. Query must join `strategy_entitlement` for platform strategies, or require `owner_tenant_id = tenant_id` for tenant-owned. Never use `SELECT * FROM strategy_definition` without entitlement or ownership filter.
- **Create / update:** Tenant may create only with `owner_kind = tenant` and `owner_tenant_id = caller_tenant`. Platform roles may create `owner_kind = platform` (separate IAM).
- **Cross-tenant IP:** Impossible by construction if every API path enforces the above; client strategy rows are never returned in another tenant’s list endpoint.

### Versioning

- Immutable versions: edits create a new `version` row; running strategies pin to a specific `strategy_definition_id` (UUID per version row).
- Deprecation: set `deprecated_at`; orchestrator refuses new bindings on deprecated versions unless override flag (admin).

## Alternatives considered

- **Separate database per tenant for strategies** — Maximum secrecy; complicates platform strategy distribution and upgrades.
- **Encrypt entire strategy table per tenant key** — Useful for regulated clients; can be layered on top without changing the ownership model.
- **Git-only registry** — Good for dev workflow; production still needs authoritative DB for entitlements and audit.

## Consequences

- **Positive:** Clear SQL patterns for “strategies I can run” vs “strategies I own.”
- **Positive:** Aligns with broker abstraction: bindings reference `broker_account_id` under the same `tenant_id`.
- **Negative:** Entitlement management UI and migrations must be built early to avoid ad-hoc sharing.

## Broker abstraction alignment

- Strategies never call brokers; the execution runtime resolves `tenant_id` → `BrokerAdapter` → `place_order`. Strategy records store no broker SDK types.

## Tech Lead handoff

- Implement repositories with mandatory `tenant_id` argument and entitlement join.
- Add integration tests: tenant A cannot `GET` tenant B’s definition by UUID guessing (404, not 403, to avoid existence leak — product decision).

## Security Architect handoff

- Classify `spec_json` / artifacts; enforce encryption and signed URLs for object storage.
- Audit log for entitlement grants/revocations.

# ADR 0004: Tenant onboarding flow

## Status

Accepted

## Context

New clients need a repeatable path from contract to live trading without manual drift or missing isolation guarantees.

## Decision

**Sequence (happy path)**

1. **Provision tenant record**

   - Create row in `tenants` with `tenant_id`, display name, status `pending`.
   - Allocate default rate-limit tier and feature flags.

2. **Namespace materialization**

   - No separate DB schema in v1; ensure RLS policies apply to new `tenant_id` (idempotent migration).
   - Optionally pre-create Redis key prefixes (lazy on first write is acceptable).

3. **Identity**

   - Create service user / API keys or OIDC subject mapping bound to `tenant_id`.
   - Dashboard login receives JWT (or session) with immutable `tenant_id` claim.

4. **Broker registration**

   - Tenant admin selects broker (`tradestation`, future values) in UI.
   - Store encrypted credentials or OAuth refresh material keyed by `(tenant_id, broker)`.
   - Run OAuth authorization code flow if required; persist tokens via adapter `authenticate` / `refresh_token` pipeline.
   - Validate: `get_account` for at least one selected `account_id` succeeds.

5. **Strategy access**

   - Grant `strategy_entitlement` rows for licensed platform strategies.
   - If tenant brings own strategies: upload/register definitions with `owner_kind = tenant`.

6. **Activation**

   - Status → `active`; enable live trading only after risk checklist (manual or automated).

7. **Monitoring**

   - Register tenant in observability (labels `tenant_id` on metrics where cardinality allows, or sampled).

## Alternatives considered

- **Fully automated self-serve signup** — Deferred until billing and KYC are defined.
- **Shared “demo” tenant** — Allowed only in non-production; production tenants always isolated.

## Consequences

- Onboarding service is the only component that creates tenants and entitlements; random API paths cannot mint tenants.
- Broker abstraction: step 4 never embeds TS URLs in generic onboarding code; call adapter interfaces only.

## Handoffs

- **Security Architect:** Threat model for OAuth state parameter, credential encryption, and admin impersonation (break-glass).
- **Orchestrator:** No jobs scheduled for `pending` tenants.

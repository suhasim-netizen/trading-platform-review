# ADR 0003: Multi-account routing (equities/options vs futures)

## Status

Accepted

## Context

Phase 1 paper trading must support **multiple broker accounts** for a single tenant:

- one account for **equities/options**
- one account for **futures** (and futures options)

The previous behavior routed all orders to a single configured account id (`TS_ACCOUNT_ID`), which can cause:

- futures orders placed into the wrong account,
- margin/exposure reporting drift,
- incorrect compliance boundaries when accounts are segregated by instrument class.

We must route orders deterministically based on **instrument type**, without embedding vendor-specific enums or SDK types into shared code.

## Decision

1. Extend the platform broker DTOs:

   - Add `InstrumentType` enum to `src/brokers/models.py`.
   - Add `instrument_type: InstrumentType` to `Order`.

2. Introduce an execution-layer `AccountRouter`:

   - New file `src/execution/account_router.py`
   - API:
     - `resolve(order: Order, tenant_id: str) -> str`
   - Behavior: returns the broker `account_id` for the order based on `order.instrument_type`.

3. Require explicit account routing at order placement time:

   - Update `BrokerAdapter.place_order` to require `account_id` as an explicit argument.
   - Update `OrderRouter` to resolve `account_id` **before** calling `place_order`.
   - Unknown instrument types raise `ValueError` (never silently route).

4. Update settings and environment configuration:

   - Add `TS_EQUITY_ACCOUNT_ID`, `TS_OPTIONS_ACCOUNT_ID`, `TS_FUTURES_ACCOUNT_ID` to `Settings`.
   - Keep `TS_ACCOUNT_ID` as **deprecated fallback only** (Phase 1 compatibility; new code must prefer explicit per-type settings).

## Routing rules (authoritative)

- `InstrumentType.EQUITY` → `settings.TS_EQUITY_ACCOUNT_ID`
- `InstrumentType.OPTIONS` → `settings.TS_OPTIONS_ACCOUNT_ID`
- `InstrumentType.FUTURES` → `settings.TS_FUTURES_ACCOUNT_ID`
- `InstrumentType.FUTURES_OPTIONS` → `settings.TS_FUTURES_ACCOUNT_ID`
- Unknown → raise `ValueError`

## Tenant isolation

- `AccountRouter.resolve(...)` requires `tenant_id` and returns an account id for that request context.
- `OrderRouter` passes `tenant_id` and `account_id` into `BrokerAdapter.place_order(...)` on every placement.
- No global “default account” is permitted for placement; routing is deterministic per order.

## Alternatives considered

1. **Single account for all instruments**
   - Rejected: violates operational requirement (separate futures account) and increases risk of incorrect routing.

2. **Infer instrument type from symbol format**
   - Rejected: brittle across brokers/venues; strategy code should declare intent explicitly.

3. **Store account routing in DB per tenant**
   - Deferred: feasible later (multi-tenant SaaS), but Phase 1 uses settings/env for simplicity and speed.

## Consequences

- **Positive:** Futures can never be accidentally routed to the equities/options account.
- **Positive:** Routing is broker-agnostic at the model layer (instrument type is platform semantic).
- **Negative:** `BrokerAdapter.place_order` signature change requires updating adapters and tests.

## Implementation checklist

- [ ] Strategy implementations set `Order.instrument_type` correctly.
- [ ] `OrderRouter` must call `AccountRouter.resolve` before placing orders.
- [ ] Environments must set `TS_EQUITY_ACCOUNT_ID`, `TS_OPTIONS_ACCOUNT_ID`, `TS_FUTURES_ACCOUNT_ID` (Phase 1).


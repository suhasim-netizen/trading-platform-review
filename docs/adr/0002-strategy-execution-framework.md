# ADR 0002: Strategy execution framework

## Status

Proposed (Phase 1 exit blocker — to be accepted after Tech Lead review)

## Context

Strategy 001 (`strategy_001_equity_momentum_sp500` v0.1.0) has passed risk review and is approved for **paper trading** under `tenant_id=director`. We need a strategy execution engine that:

- Converts a **live bar feed** into **signals**, and signals into **orders** via `BrokerAdapter` (broker-agnostic).
- Enforces **risk limits before order placement** (paper limits from the approval doc).
- Maintains strict **tenant isolation** for execution state and persistence.
- Runs **paper and live** on the same code paths, changing only configuration (broker endpoints/credentials selected by trading mode).

The codebase already contains:

- `BrokerAdapter` contract (`src/brokers/base.py`) with a bar stream (`stream_bars`) and execution methods (`place_order`, `cancel_order`, `get_positions`, and `stream_order_updates`).
- A bar pipeline (`src/data/pipeline.py`) that consumes `BrokerAdapter.stream_bars(...)` and publishes tenant-scoped OHLCV bars to Redis channels (`{tenant_id}:bars:{symbol}:{interval}`).

## Decision

Adopt an **event-driven, tenant-scoped execution loop** with four explicit components:

- **StrategyRunner**: subscribes to tenant-scoped bar events; generates `Signal` events.
- **OrderRouter**: converts signals to platform `Order` objects, enforces risk limits **pre-trade**, and routes through `BrokerAdapter`.
- **PositionTracker**: maintains current positions and P&L per `(tenant_id, trading_mode, account_id, strategy_id)`, updated from order updates/fills and/or periodic `get_positions`.
- **ExecutionLogger**: persists all signals, orders, and fills (order updates) to the database with mandatory `tenant_id` scoping.

Paper trading is implemented as **the same engine**, parameterized by `trading_mode="paper"` (selects paper broker config + endpoints); live uses `trading_mode="live"`.

## 1) Execution loop architecture

### Data flow (conceptual)

**Bar → Signal → Order → Fill → Position**

1. **Bar ingest**
   - Source: Redis pub/sub channel published by `MarketDataPipeline`:
     - `bars_channel(tenant_id, symbol, interval)` → e.g. `director:bars:AAPL:1d`
   - Payload: platform `Bar` (broker-normalized), including `tenant_id` and timestamp fields.

2. **Signal generation**
   - StrategyRunner maintains strategy state (warmup windows, universe selection caches, regime flags like VIX).
   - On bar events (and scheduled “rebalance ticks”), Runner emits a **Signal** for a target portfolio change:
     - Example signal types: `TARGET_WEIGHTS`, `ENTER`, `EXIT`, `FLATTEN`, `REBALANCE`.
   - Signal is always annotated with:
     - `tenant_id`, `trading_mode`, `strategy_id`, optional `account_id`, `generated_at`.

3. **Pre-trade risk & routing**
   - OrderRouter receives Signal and asks PositionTracker for:
     - current positions, latest prices (if needed), current NAV and drawdown, and open order exposure
   - Router enforces risk limits **before** placing any order (see §4).
   - Router translates approved intents into one or more `brokers.models.Order` objects and calls:
     - `await adapter.place_order(order, tenant_id=...)`

4. **Fill / order update handling**
   - Source: `BrokerAdapter.stream_order_updates(account_id, tenant_id)` (preferred) and/or polling fallbacks.
   - Each `OrderUpdate` is mapped to internal “fill / lifecycle” events.
   - PositionTracker updates holdings, average cost, realized/unrealized P&L inputs.

5. **Persistence**
   - ExecutionLogger records:
     - every bar-derived signal decision (even if risk blocks it),
     - every order placement/cancel request and receipt,
     - every order update / fill,
     - snapshots/metrics used for risk decisions (NAV, drawdown, daily P&L, largest weight).

### Loop topology (per tenant)

For each `(tenant_id, trading_mode, strategy_id)` we run an isolated loop:

```
Redis bars (tenant-scoped) --> StrategyRunner --> Signal bus --> OrderRouter --> BrokerAdapter
                                                  |                 |
                                                  v                 v
                                           ExecutionLogger     PositionTracker
                                                  ^
                                                  |
                                    BrokerAdapter.stream_order_updates (tenant-scoped)
```

The “signal bus” may be an in-process `asyncio.Queue` in Phase 1.

## 2) Component design

### StrategyRunner

**Responsibilities**

- Load strategy definition (code reference) and configuration (tenant-scoped).
- Subscribe to required bar channels (universe symbols + required external series like VIX).
- Maintain strategy state and emit Signals.

**Key inputs**

- `tenant_id`, `trading_mode`, `strategy_id`, `account_id`
- Redis client (subscriber)
- PositionTracker (read-only interface for current state)
- ExecutionLogger

**Notes for Strategy 001**

- Uses daily bars; triggers rebalances on:
  - monthly schedule (spec) and risk doc’s weekly rebalance constraint (see §4 for how to reconcile: weekly *risk-driven* rebalance overrides monthly *alpha* rebalance).
- Requires VIX series; treat VIX as a symbol-like external feed published to a separate tenant-scoped channel (implementation detail to Data Engineer).

### OrderRouter

**Responsibilities**

- Convert Signals into concrete `Order` objects.
- Enforce risk limits before placing orders.
- Route to BrokerAdapter and normalize receipts/errors.

**Key inputs**

- Signal events (tenant-scoped)
- Risk policy config (from approval doc, versioned per strategy)
- BrokerAdapter instance (resolved per tenant+mode)
- PositionTracker (state)
- ExecutionLogger

**Output**

- `OrderReceipt` and/or raised broker exceptions mapped to platform errors.

### PositionTracker

**Responsibilities**

- Maintain current positions and derived metrics:
  - positions by symbol
  - exposure, largest position weight
  - strategy NAV and peak-to-trough drawdown
  - daily P&L
- Apply updates from fills/order updates and reconcile periodically against `get_positions` to avoid drift.

**Tenant isolation**

- All internal maps keyed by `(tenant_id, trading_mode, account_id, strategy_id)`; no global mutable state shared across tenants.

### ExecutionLogger

**Responsibilities**

- Persist immutable event records:
  - signal events
  - order intents + placed/cancelled receipts
  - order updates / fills
  - risk evaluation outcomes (allowed/blocked + reason)

**Tenant isolation**

- Every DB write includes `tenant_id` and `trading_mode` (paper/live isolation).

## 3) Paper trading mode

Paper trading differs from live only by **configuration**, not code path:

- Engine runs with `trading_mode="paper"`.
- BrokerAdapter instance is created from the tenant’s broker configuration for paper mode:
  - paper endpoints/base URLs and credentials
- The StrategyRunner/Router/Tracker/Logger are identical; the router still calls `BrokerAdapter.place_order`.

This ensures:

- identical risk enforcement in paper and live,
- minimal chance of “paper-only behavior” masking live issues,
- simpler operational promotion from paper → live.

## 4) Risk limit enforcement (pre-trade)

Risk limits from `docs/risk/risk_approval_strategy_001_v0.1.0.md` must be enforced **in OrderRouter before calling `place_order`**.

### Required controls (Strategy 001 — paper)

- **Max drawdown trigger**: suspend strategy at drawdown ≤ **-25%** (peak-to-trough strategy NAV)
  - Behavior: block new orders; optionally flatten (policy toggle) and mark strategy state `SUSPENDED`.
- **Daily loss limit**: if daily P&L ≤ **-2.5%** of strategy NAV
  - Behavior: block new orders for remainder of day; allow cancels/flatten if configured.
- **Max position size**: **12%** of strategy NAV per position
  - Behavior: block orders that would breach; allow orders that *reduce* exposure.
- **Max concurrent positions**: **10**
  - Behavior: block entries that exceed; allow swaps if net count remains ≤ 10.
- **VIX circuit breaker**: OFF when VIX > **30**, re-enable only when VIX ≤ **28**
  - Behavior: block entries/upsizes while OFF; allow flattening.
- **Rebalance frequency constraint**: **weekly**, or earlier if any position breaches 12%
  - Interpretation:
    - Alpha rebalance cadence remains monthly for Strategy 001, but **risk-driven “rebalance”** is allowed weekly to enforce caps and reduce drift.

### Enforcement point in the loop

- StrategyRunner emits Signals (desired targets).
- OrderRouter performs:
  1. risk state update using PositionTracker metrics (NAV, drawdown, daily P&L, largest weight)
  2. regime guard check (VIX)
  3. order sizing / constraint solving (caps, max positions)
  4. **only then** calls `BrokerAdapter.place_order(...)`

All blocked actions must be logged (ExecutionLogger) with a stable `risk_block_reason`.

## 5) Tenant isolation

Non-negotiable enforcement across the framework:

- Runner/Router/Tracker/Logger constructors require explicit `tenant_id` and `trading_mode` (no defaults).
- Redis channels are always tenant-prefixed (e.g. `{tenant_id}:bars:...`).
- BrokerAdapter calls always pass `tenant_id` and resolve tenant-scoped credentials.
- PositionTracker state is stored in tenant-scoped in-memory structures and persisted with tenant_id filters.
- ExecutionLogger writes to DB tables that include `tenant_id` (and `trading_mode`) and must never query/write without those filters.

Failure mode policy:

- If any event is observed with a mismatched `tenant_id`, the component must **drop and log** (never “best effort” route).

## 6) File structure (Tech Lead must create)

Create these exact files (Phase 1):

- `src/execution/runner.py` — `StrategyRunner` (async task; consumes bars; emits signals)
- `src/execution/router.py` — `OrderRouter` (risk checks + order placement via BrokerAdapter)
- `src/execution/tracker.py` — `PositionTracker` (tenant-scoped positions/P&L/NAV/drawdown)
- `src/execution/logger.py` — `ExecutionLogger` (DB persistence for signals/orders/fills)
- `src/execution/__init__.py` — exports the public execution framework surface

Note: The “signal” type may be introduced as a small internal model (pydantic/dataclass) under `src/execution/` if needed; it must remain broker-agnostic and tenant-scoped.

## Alternatives considered

1. **Direct broker streaming inside StrategyRunner (no Redis pipeline)**
   - Pros: fewer moving parts.
   - Cons: each strategy duplicates subscription logic; harder to enforce DQ checks once; difficult to share data across multiple consumers (dashboards, backtests, audit).
   - Rejected: we already have `MarketDataPipeline` publishing normalized bars; standardizing on that reduces broker coupling.

2. **Monolithic “StrategyEngine” class (runner+router+tracker+logger combined)**
   - Pros: simple to build.
   - Cons: mixes responsibilities; risk controls become hard to test; tenant isolation boundaries blur; discourages reuse across strategies.
   - Rejected: separation improves auditability and security review.

3. **Post-trade risk checks (place first, validate later)**
   - Rejected: violates the risk requirement and increases blast radius (you cannot untrade a filled order).

4. **Schema-per-tenant for execution events**
   - Non-goal for Phase 1 (see database schema decision); row-level + RLS is sufficient initially.

## Consequences

- **Positive:** Broker abstraction is preserved: only OrderRouter touches `BrokerAdapter`.
- **Positive:** Risk controls are centralized and testable.
- **Positive:** Tenant isolation is explicit in constructor signatures, channel naming, and DB writes.
- **Negative:** Requires disciplined event schemas (Signal and execution event records) and careful async task orchestration.

## Implementation notes (handoff)

### Tech Lead

- Implement the file structure in §6 and keep broker imports constrained to `brokers/`.
- Ensure the runner subscribes only to `{tenant_id}:...` channels.
- Add tests for:
  - risk blocks at thresholds (daily loss, drawdown, max weight, max positions)
  - tenant mismatch drops (bar with wrong tenant_id is ignored)

### Data Engineer

- Add event tables or extend existing tables to record signals and order updates with `(tenant_id, trading_mode, strategy_id)` scoping.
- Ensure indexes include `(tenant_id, trading_mode, created_at)` on high-write execution event tables.

### Security Architect

- Validate tenant isolation boundaries and that `BrokerAdapter` credential resolution cannot cross tenant IDs.
- Confirm logging/redaction policy for broker payloads and ciphertext (no secrets in logs).


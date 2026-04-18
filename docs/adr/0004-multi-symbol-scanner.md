# ADR 0004: Multi-symbol scanner engine

## Status

Proposed

## Context

The platform is expanding to **multi-strategy intraday** trading. Strategies need a **single tenant-scoped process** that:

- Subscribes to **many symbols at once** (budget: up to **30 equities**, **2 futures**, and **options chain** coverage as defined by product).
- Consumes **5-minute bars** per symbol (normalized `Bar` with `interval="5m"`).
- Runs **independent signal evaluation** per symbol (each symbol may map to one or more strategy bindings).
- Emits signals to the existing **`OrderRouter`**, with correct **`Order.instrument_type`** and **`account_id`** (via **`AccountRouter.resolve`** — see ADR 0003).
- Keeps **all state keyed by `tenant_id`** — no cross-tenant leakage.

This ADR does not prescribe vendor SDK usage; all broker access remains behind **`BrokerAdapter`**.

## Decision

Introduce a **MultiSymbolScanner** (or **ScannerEngine**) service per `(tenant_id, trading_mode)` that:

1. **Maintains a subscription registry** — which symbols are active, which strategy modules evaluate them, and which `instrument_type` applies when building `Order`.
2. **Obtains 5m bars** via **`BrokerAdapter.stream_bars(symbol, "5m", tenant_id)`** (one async stream per symbol **or** a broker-multiplexed stream if the concrete adapter supports batching — see alternatives).
3. **Processes each completed bar** in an **isolated async task** or **per-symbol async queue** so one slow symbol does not block others.
4. **Dispatches** resulting `Signal` (execution framework) or directly constructs `Order` intents to **`OrderRouter.route(...)`** with `instrument_type` set and **`AccountRouter`** applied inside the router.

### Concurrency and WebSocket / stream management

**Key design decision — one stream per symbol vs multiplex:**

- **Default (Phase 1): one `stream_bars` async iterator per symbol**, each driven by a **dedicated asyncio Task**. Rationale: matches the existing `BrokerAdapter` contract (`stream_bars(symbol, interval, tenant_id)`), keeps adapter implementations simple, and isolates failures per symbol.
- **Cap enforcement:** the scanner refuses to start beyond configured max symbols (30+2+options scope) and logs `scanner.subscription_limit_exceeded`.
- **Back-pressure:** each per-symbol task pushes **completed bars only** into an internal **`asyncio.Queue[Bar]`** bounded per symbol (e.g. maxdepth 2–5). If a strategy evaluation falls behind, **drop intermediate bars** for that symbol with a metric + log (intraday scanners prefer **latest bar** over stale backlog).

**If the broker supports a single WebSocket with many topics** (common for vendors):

- The **concrete adapter** may implement **multiplexed** `stream_bars` by spawning one network connection and **fan-out** to per-symbol async queues internally. Platform code still sees **per-symbol** streams at the `BrokerAdapter` boundary **or** a documented optional `stream_bars_batch` extension on the adapter (future ADR). **Platform scanner must not import vendor modules.**

### Preventing one symbol from blocking others

- **No shared CPU-heavy work on the event loop thread:** signal evaluation runs in:
  - pure async coroutines for light logic, or
  - `asyncio.to_thread(...)` / `run_in_executor` for CPU-heavy features (e.g. large option chain scoring), **per symbol**.
- **Per-symbol locks:** only one evaluation at a time **per (tenant_id, symbol)** to avoid duplicate orders from overlapping bars.
- **Order placement** remains serialized through **`OrderRouter`** (tenant-scoped instance) which already enforces risk **before** `BrokerAdapter.place_order`.

### Dispatching signals from different strategies

**Key design decision — explicit bindings:**

- Configuration (DB or tenant config) defines **`ScannerBinding`** rows:
  - `tenant_id`, `trading_mode`, `symbol`, `strategy_id`, `instrument_type`, optional `priority`.
- On each bar, the scanner calls **only** the strategy handlers registered for that symbol.
- If **multiple strategies** subscribe to the same symbol:
  - **default:** evaluate **in parallel** (async gather) and emit **independent** signals; `OrderRouter` + risk limits decide what actually trades.
  - **optional:** `priority` + **dedupe window** (e.g. 1s) to reduce duplicate opposite signals — product decision, documented in binding schema.

All emitted orders must carry **`instrument_type`** so **`AccountRouter`** routes to the correct TradeStation account (ADR 0003).

## Alternatives considered

| Alternative | Why not chosen (for now) |
|-------------|---------------------------|
| Single task polling REST for each symbol | High latency, rate limits; poor fit for 30+ names. |
| One global queue for all bars | Head-of-line blocking; violates isolation goal. |
| Strategy code imports broker directly | Breaks BrokerAdapter abstraction rule. |
| Redis-only bar fan-in without adapter | Bypasses normalization/DQ in `MarketDataPipeline`; duplicates logic. |

## Integration points

- **`BrokerAdapter.stream_bars`** — source of truth for normalized **`Bar`**.
- **`MarketDataPipeline`** (optional) — may **also** publish bars to Redis for dashboards; scanner may consume **either** adapter stream **or** Redis tenant channels — pick **one** per deployment to avoid double-processing (decision: **scanner consumes adapter streams** for execution path; Redis remains observability/UI).
- **`OrderRouter` + `AccountRouter` + `ExecutionLogger` + `PositionTracker`** — unchanged contract; scanner only supplies correctly typed `Order` / `Signal`.

## Consequences

- **Positive:** Horizontal scaling path — add scanner replicas **per tenant** with partitioned symbol sets (future).
- **Positive:** Clear failure domain per symbol.
- **Negative:** Up to ~32 concurrent streams — must monitor connection limits and broker throttling; may require multiplexed adapter implementation later.

## Follow-ups (Tech Lead)

- Implement `src/scanner/` (or `src/execution/scanner.py`) with unit tests: tenant mismatch drops, per-symbol isolation, max symbol cap.
- Metrics: `scanner_bar_lag_seconds`, `scanner_dropped_bars`, `scanner_active_symbols`.

# ADR 0005: Intraday position manager

## Status

Proposed

## Context

Multi-strategy intraday trading requires **intraday-specific lifecycle rules** that differ from swing/overnight sleeves:

- **Separate tracking** of intraday vs overnight/swing exposure (same broker account may hold both; semantics differ).
- **Hard flat** before the cash session close window (policy: **3:55pm America/New_York** for equities; futures have their own session — see below).
- **Pattern Day Trader (PDT)** surveillance for US equity accounts &lt; $25k: **3 day trades** per **rolling 5 business-day** window; block new opening day trades when the count would exceed 3; **alert** when **2** day trades are used (1 away from limit).

This component must integrate with existing **`PositionTracker`** and **`ExecutionLogger`** without bypassing **`BrokerAdapter`**.

## Decision

Introduce an **`IntradayPositionManager`** (IPM) scoped by **`(tenant_id, trading_mode, account_id)`** — one instance per broker account the tenant uses for intraday strategies.

### Responsibilities

1. **Tag positions and orders** with `holding_period: "intraday" | "swing"` (stored in execution logs and/or `Order.metadata` / DB columns). **`PositionTracker`** gains an optional **view** or **overlay** that filters to `intraday` tags for risk metrics that should not mix with overnight sleeves.

2. **Hard close at 3:55pm ET (equities/options on US cash session)**  
   - Scheduler (APScheduler / cron / internal loop) triggers **`flatten_intraday(tenant_id, ...)`** which:
     - builds reduce-only / market orders for all **intraday-tagged** open symbols via **`OrderRouter`** (respects risk, but **close policy overrides** new-entry blocks — see §3).
   - **Futures:** configurable session end per product (e.g. ES RTH vs ETH). Default policy: **same wall-clock job** is insufficient; IPM uses a **product session calendar** (Data Engineer feed) — **v1:** configurable **flatten time per `instrument_type`** with ES/MES example **16:00 ET** (illustrative — must match broker + product).

3. **PDT rolling window (equity day trades)**  
   - Maintain a **ring buffer of day-trade events** (date + symbol + order ids) for the **past 5 business days** (NYSE calendar).
   - **Day trade definition (US cash equity):** opening and closing the same symbol on the same day (same-day round trip). Implementation derives from **`ExecutionLogger` / fills** when both buy and sell legs occur same session.
   - **Block:** when placing an order that would **open** a new position (or add) and would create a **3rd** day trade in the rolling window **and** account equity &lt; $25,000 — reject in **`OrderRouter`** **before** adapter call, with reason `pdt_limit`.
   - **Alert:** when count **reaches 2** and a new day trade would reach 3 — emit **`DirectorAlert`** (email/webhook/internal queue) — `pdt_warning_one_remaining`.

4. **Integration with `PositionTracker`**  
   - IPM **does not duplicate** quantity math long-term; it **subscribes** to fill events from **`ExecutionLogger`** / order updates and updates **intraday aggregates** (net per symbol, day trade count).
   - **`PositionTracker`** remains source for NAV/drawdown used by **`OrderRouter`**; IPM adds **intraday-specific** fields (e.g. intraday realized P&amp;L).

5. **Integration with `ExecutionLogger`**  
   - Every flatten, PDT block, and alert is **audited** with `tenant_id`, timestamps, and rule version.

## Alternatives considered

| Alternative | Tradeoff |
|-------------|----------|
| Only use broker-reported “day trade count” | Convenient but not portable across brokers; harder in paper sim. |
| Flatten via broker “close all” button API | Not portable; keep **explicit orders** via `BrokerAdapter`. |
| Single PositionTracker with no tagging | Mixes intraday and swing — breaks risk and reporting. |

## Policy details (authoritative for implementation)

- **Hard close time:** `15:55` **America/New_York** for **equity/options intraday** positions unless strategy metadata overrides (must still be before session close).
- **PDT:** rolling **5 business days**, **max 3** day trades for accounts **under $25k** — **block** new day trades at limit; **warn** at **2** day trades used when next would be **3rd** (user request: alert when **1 away** — interpreted as **2** used, **1** remaining before block).

## Consequences

- **Positive:** Clear separation of intraday risk from swing portfolios.
- **Positive:** PDT logic centralized; easier audits.
- **Negative:** Requires **accurate fill timestamps** and **US calendar**; futures session rules add complexity.

## Integration points

- **`OrderRouter`** — add pre-trade hooks: `pdt_check`, `intraday_flatten_override` (close-outs allowed even when “new entries” blocked).
- **`ExecutionLogger`** — source of truth for fills and day-trade classification.
- **`BrokerAdapter`** — only path for placing flatten orders; **no** direct TS calls.

## Follow-ups (Tech Lead / Data Engineer)

- DB columns or JSON for `holding_period` and PDT event log.
- NYSE calendar library or exchange calendar table.

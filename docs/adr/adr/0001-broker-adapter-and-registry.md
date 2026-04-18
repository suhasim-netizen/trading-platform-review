# ADR 0001: Broker adapter interface and registry

## Status

Accepted

## Context

The platform must remain broker-agnostic so that TS, IBKR, Alpaca, or future venues can be swapped without touching strategy, risk, or portfolio logic. All market access and execution must flow through a single port. Tenants may each use a different broker configuration; credentials and streams must never be mixed across `tenant_id` values.

## Decision

Amended 2026-04-14 — method names corrected to match implemented contract.

1. **Contract** — Define `BrokerAdapter` as an abstract base class in `src/brokers/base.py`. All concrete implementations live under `src/brokers/<vendor>/` and are the only modules that may speak vendor APIs or SDKs.

2. **Canonical methods** (plus OAuth lifecycle required for real brokers):

   | Method | Role |
   |--------|------|
   | `authenticate` / `refresh_token` | Obtain and renew access; map `BrokerCredentials` to `AuthToken`. |
   | `get_quote(symbol, tenant_id)` | Point-in-time top of book / last. |
   | `stream_quotes(symbols, tenant_id)` | Async stream of `Quote`. |
   | `place_order(order, tenant_id)` | Submit execution; returns `OrderReceipt`. |
   | `cancel_order(order_id, tenant_id)` | Cancel; returns `CancelReceipt`. |
   | `get_positions(account_id, tenant_id)` | Open positions. |
   | `get_account(account_id, tenant_id)` | Account snapshot. |
   | `stream_order_updates(account_id, tenant_id)` | Async stream of `OrderUpdate`. |

3. **Platform models** — All inputs/outputs use `src/brokers/models.py` types (`Quote`, `Bar`, `Order`, `Account`, etc.). Vendor JSON is confined to optional `raw` bags that remain tenant-scoped and must not leak into strategy code.

4. **Registry** — `src/brokers/registry.py` maps a logical name from tenant configuration (e.g. `broker: tradestation`) to a concrete class via `register_adapter` at application startup. Resolution uses `resolve_adapter_class` / `create_adapter`; no `if broker == "tradestation"` branches outside adapter packages.

5. **TS adapter (v1)** — Single reference implementation:

   - REST: OAuth token exchange, refresh, accounts, balances, positions, orders, market data where v3 exposes REST quotes/bars.
   - WebSockets: multiplex streams per tenant session; map payloads to `Quote` and `OrderUpdate`; enforce `tenant_id` on every outbound subscription and inbound dispatch.
   - Internal HTTP/WS clients must not be imported outside `brokers/tradestation/`.

## Alternatives considered

- **Per-tenant subprocess broker workers** — Strong isolation, higher ops cost; deferred until scale or compliance demands it.
- **Single giant “broker facade” with inline vendor branches** — Rejected; violates “zero changes to platform logic” when adding a broker.
- **Schema-per-tenant for broker audit logs** — Rejected for v1; shared tables with `tenant_id` + RLS (see ADR 0002) are sufficient initially.

## Consequences

- **Positive:** Tech Lead can implement `TSBrokerAdapter` in isolation; adding IBKR/Alpaca is register + new package only.
- **Positive:** Reviews can grep for forbidden imports (`tradestation`, `ib_insync`, `alpaca`) outside `brokers/<vendor>/`.
- **Negative:** Adapters must normalize interval names and event shapes; some loss of vendor-specific nuance unless carried in `raw`.
- **Multi-tenancy:** Every adapter method accepts `tenant_id` (or embeds it on returned models) so credential lookup and logging stay namespaced.

## Tech Lead handoff

- Implement `TSBrokerAdapter(BrokerAdapter)` and call `register_adapter("tradestation", TSBrokerAdapter)` during app startup.
- Do not add broker parameters to `Order` beyond platform fields; map to TS order types inside the adapter.
- Contract tests: mock HTTP/WS and assert mapping to platform models.

## Security Architect handoff

- Document OAuth redirect URLs per environment; tokens at rest encrypted per `tenant_id` (see ADR 0002).
- Adapter must not log raw access tokens.

## Compliance checklist (architecture review)

- [ ] No `import` of vendor modules outside `src/brokers/<vendor>/`.
- [ ] No SQL or cache access in adapters except through injected, tenant-scoped repositories (if any).
- [ ] `stream_order_updates` events include `tenant_id` and are not broadcast on shared channels without a tenant prefix.

Contract frozen: 2026-04-14. Any future changes require a new ADR.

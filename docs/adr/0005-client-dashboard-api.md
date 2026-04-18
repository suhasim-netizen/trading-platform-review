# ADR 0005: Client dashboard API

## Status

Accepted

## Context

The dashboard exposes portfolio, orders, strategies, and health to authenticated users. Responses must never include another tenant’s data, even under error conditions.

## Decision

**FastAPI (or equivalent) service with tenant-first dependencies and broker access only via injected `BrokerAdapter`.**

### Cross-cutting middleware / dependencies

1. Authenticate request → extract `tenant_id` (required).
2. Reject if `tenant_id` not in deployment allow-list (when configured).
3. Set `request.state.tenant_id` and contextvar `current_tenant_id`.
4. Open DB session with `SET app.tenant_id = '<uuid>'` (RLS) when using PostgreSQL.
5. Resolve `BrokerAdapter` via registry: `create_adapter(tenant.broker, tenant_id=..., ...)` using stored secrets.

### Endpoint groups (contract sketch)

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/v1/me` | Caller profile + `tenant_id` + entitlements summary |
| `GET` | `/v1/accounts` | List accounts for tenant via adapter or cached mirror |
| `GET` | `/v1/accounts/{account_id}` | `get_account`; 404 if account not linked to tenant |
| `GET` | `/v1/accounts/{account_id}/positions` | `get_positions` |
| `GET` | `/v1/orders` | List from DB mirror filtered by `tenant_id` + optional account |
| `POST` | `/v1/orders` | Validate body → `place_order` |
| `POST` | `/v1/orders/{order_id}/cancel` | `cancel_order` |
| `GET` | `/v1/quotes/{symbol}` | `get_quote` |
| `GET` | `/v1/strategies` | Registry list with entitlement join only |
| `GET` | `/v1/strategies/{id}` | Single definition if entitled or owner |
| `WS` | `/v1/stream/quotes` | Query params: symbols; proxies `stream_quotes` |
| `WS` | `/v1/stream/orders` | Query param: account_id; proxies `stream_order_updates` |

### Rate limiting

- Keyed by `tenant_id` (and optionally API key id) at the gateway.

### Error handling

- Do not echo internal broker errors verbatim to clients; map to stable error codes.
- 404 for any resource id not belonging to tenant (avoid id enumeration).

## Alternatives considered

- **GraphQL single endpoint** — Flexible but easier to accidentally over-fetch; REST + WS chosen for v1 clarity.
- **Per-tenant API subdomains** — Optional DNS convenience; authorization still relies on `tenant_id` claim, not host name alone.

## Consequences

- WebSocket handlers must re-validate `tenant_id` on connection and on each subscription message.
- **Broker abstraction:** Route handlers import `BrokerAdapter` type and registry only, never `tradestation` modules.

## Tech Lead handoff

- Implement routes in `src/api/` with shared `Depends(get_tenant_context, get_broker_adapter)`.
- Contract tests: two tenants, assert A cannot read B’s orders with B’s UUIDs.

## Security Architect handoff

- CORS, CSRF (if cookies), and WS authentication (query token vs header tradeoffs).

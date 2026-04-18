# BrokerAdapter specification (Phase 1)

This document is the authoritative contract for the platform broker port. Core services, strategies, risk engines, and dashboards must depend only on `BrokerAdapter` and the DTOs in `src/brokers/models.py`, never on vendor SDKs or vendor-specific enums outside `src/brokers/<vendor>/`.

**Breaking change note:** Earlier drafts used `stream_bars` / `stream_account_updates` and a `Bar` / account-update union. Phase 1 standardizes on `stream_quotes` / `stream_order_updates` and the models listed below. Update any callers or adapters accordingly.

---

## Tenant scoping (all methods)

- Every method that touches market data, accounts, or orders receives either `tenant_id` directly or a `BrokerCredentials` / `AuthToken` that already includes `tenant_id`.
- Adapters must resolve credentials, HTTP clients, and WebSocket subscriptions **only** for that tenant (e.g. load encrypted tokens keyed by `tenant_id`, never a process-wide singleton token shared across tenants).
- Every returned model that represents tenant-owned or tenant-visible state must carry `tenant_id` where applicable (`Quote`, `Account`, `OrderReceipt`, `CancelReceipt`, `Position`, `OrderUpdate`). Adapters set these from the method argument or authenticated session, not from untrusted caller fields inside `Order` alone.

---

## Exception types (`src/brokers/exceptions.py`)

| Type | When to raise |
|------|----------------|
| `BrokerAuthError` | Invalid credentials, revoked access, failed token exchange, missing token for tenant. |
| `BrokerTokenExpiredError` | Access token expired and refresh failed or is impossible. |
| `BrokerNetworkError` | Transient connectivity, timeouts, DNS. |
| `BrokerRateLimitError` | Broker rejected due to throttling; callers may retry with backoff. |
| `BrokerValidationError` | Malformed platform request, unexpected response shape, missing required fields after mapping. |

Adapters should not leak raw HTTP bodies or SDK exceptions through the public API; map them to the types above and optional logs (without secrets).

---

## Methods

### `async def authenticate(credentials: BrokerCredentials) -> AuthToken`

**Purpose:** Initial session establishment (e.g. OAuth authorization-code exchange or API key bootstrap defined by the concrete adapter).

**Inputs:** `BrokerCredentials` — must include `tenant_id`; optional OAuth fields (`client_id`, `client_secret`, `authorization_code`, `redirect_uri`); `extra` allowed for adapter-specific non-secret hints.

**Outputs:** `AuthToken` bound to the same `tenant_id`.

**Errors:** `BrokerAuthError`, `BrokerValidationError`, `BrokerNetworkError`.

**Idempotency:** Not idempotent; each call may mint new tokens. Callers should persist results per tenant and prefer `refresh_token` when appropriate.

**Tenant:** Use `credentials.tenant_id` for all storage keys and audit context.

---

### `async def refresh_token(token: AuthToken) -> AuthToken`

**Purpose:** Renew an access token using refresh material or broker-specific rotation.

**Inputs:** `AuthToken` with `tenant_id` and refresh fields as required by the adapter.

**Outputs:** New `AuthToken` (updated `access_token`, `expires_at`, etc.).

**Errors:** `BrokerTokenExpiredError`, `BrokerAuthError`, `BrokerNetworkError`, `BrokerValidationError`.

**Idempotency:** Multiple successful refreshes may invalidate earlier access tokens; callers should serialize refresh per tenant or use locking.

**Tenant:** Must not change `tenant_id` on the token; reject cross-tenant misuse.

---

### `async def get_quote(symbol: str, tenant_id: str) -> Quote`

**Purpose:** Point-in-time quote snapshot for a symbol.

**Inputs:** Normalized `symbol` (adapter maps to venue symbology); `tenant_id` for credential resolution.

**Outputs:** `Quote` with `tenant_id` populated and vendor-specific details only under `raw`.

**Errors:** `BrokerValidationError`, `BrokerAuthError`, `BrokerNetworkError`, `BrokerRateLimitError`.

**Idempotency:** Safe to repeat; last-write-wins semantics for caching layers.

**Tenant:** Set `Quote.tenant_id` to the method argument.

---

### `async def get_account(account_id: str, tenant_id: str) -> Account`

**Purpose:** Snapshot of balances / buying power / equity for a brokerage account.

**Inputs:** Platform or broker `account_id` that the tenant is allowed to access; `tenant_id`.

**Outputs:** `Account` with `tenant_id` set.

**Errors:** `BrokerAuthError`, `BrokerValidationError`, `BrokerNetworkError`.

**Idempotency:** Safe to repeat.

**Tenant:** Verify the account belongs to the tenant before returning (mapping may live in platform DB; adapter may rely on broker API returning only linked accounts).

---

### `async def place_order(order: Order, tenant_id: str) -> OrderReceipt`

**Purpose:** Submit an order.

**Inputs:** Platform `Order` (side, type, TIF, prices, etc.); `tenant_id`.

**Outputs:** `OrderReceipt` with broker `order_id`, `tenant_id`, and `status`.

**Errors:** `BrokerValidationError`, `BrokerAuthError`, `BrokerRateLimitError`, `BrokerNetworkError`.

**Idempotency:** **Not** idempotent unless the caller supplies a stable `client_order_id` **and** the adapter maps it to the broker’s idempotency mechanism. Document broker behavior in the concrete adapter; platform should treat duplicate submissions as a business decision.

**Tenant:** `Order` does not carry `tenant_id`; scope strictly from the `tenant_id` argument.

---

### `async def cancel_order(order_id: str, tenant_id: str) -> CancelReceipt`

**Purpose:** Request cancellation of an open order.

**Inputs:** Broker `order_id`; `tenant_id`.

**Outputs:** `CancelReceipt`.

**Errors:** `BrokerValidationError` (unknown order), `BrokerAuthError`, `BrokerNetworkError`.

**Idempotency:** Repeated cancels for an already terminal order should return a stable outcome (`cancelled=True` or validation) where the broker allows; adapters normalize behavior.

**Tenant:** Resolve credentials only for `tenant_id`; never cancel another tenant’s order.

---

### `async def get_positions(account_id: str, tenant_id: str) -> list[Position]`

**Purpose:** List open positions for the account.

**Inputs:** `account_id`, `tenant_id`.

**Outputs:** List of `Position` with `tenant_id` set.

**Errors:** `BrokerAuthError`, `BrokerValidationError`, `BrokerNetworkError`.

**Idempotency:** Safe to repeat.

**Tenant:** Each `Position.tenant_id` must match the argument.

---

### `def stream_quotes(symbols: list[str], tenant_id: str) -> AsyncIterator[Quote]`

**Purpose:** Push or poll-driven stream of quote updates for the given symbols.

**Inputs:** List of symbols; `tenant_id`.

**Outputs:** Async iterator yielding `Quote` with `tenant_id` set on each item.

**Errors:** Failures may surface as raised exceptions on iteration start or mid-stream; use the same exception types. Document whether the iterator ends cleanly on auth failure.

**Idempotency:** Each subscription is a new stream; not idempotent across reconnects.

**Tenant:** Subscriptions and credentials must be isolated per `tenant_id`. Implementations often use an inner `async def` generator (`async def _gen(): ... yield quote`) and return `_gen()` from this synchronous method so callers use `async for`.

---

### `def stream_order_updates(account_id: str, tenant_id: str) -> AsyncIterator[OrderUpdate]`

**Purpose:** Stream of order lifecycle updates (fills, cancels, rejections).

**Inputs:** `account_id`, `tenant_id`.

**Outputs:** Async iterator of `OrderUpdate` with `tenant_id` set; `account_id` on each event when known.

**Errors:** Same as streaming quotes.

**Idempotency:** New stream per call; reconnect policies are adapter-defined.

**Tenant:** Filter events to the tenant’s account only.

---

## Adding a second broker (no core logic changes)

1. Create `src/brokers/<vendor>/` with a class implementing every `BrokerAdapter` method using only vendor APIs inside that package.
2. Register the implementation at startup: `register_adapter("<logical_name>", <AdapterClass>)` from `src/brokers/registry.py`.
3. Store per-tenant `broker: <logical_name>` and secrets in tenant configuration (not hardcoded in strategies).
4. Instantiate via `create_adapter(broker, **kwargs)` or `resolve_adapter_class` + constructor in application wiring.
5. Do not import `src/brokers/<vendor>/` from strategy, risk, or generic API modules—only from composition root or broker factory code.

Concrete adapter packages may mention vendor API paths in comments or private constants; shared models and this interface remain broker-agnostic.

---

## Reference implementation layout

The first concrete adapter may live under `src/brokers/tradestation/` (package path only). No vendor-specific identifiers are required in `base.py`, `models.py`, or `exceptions.py`.

# ADR 0006: Options chain integration (BrokerAdapter extension)

## Status

Proposed

## Context

Intraday and multi-leg strategies need **options chain discovery**, **strike selection**, and **options order placement** without leaking vendor types into shared code. Today, **`BrokerAdapter`** covers equities/futures-style `Order` and `stream_bars`; options require additional **structured contracts** and **chain snapshots**.

## Decision

### 1) Extend `BrokerAdapter` (conceptual interface)

Add **optional capability** methods (implement on concrete adapters; callers check `hasattr` or a small `Capabilities` protocol — future refinement):

| Method | Purpose |
|--------|---------|
| `async def get_options_chain(self, symbol: str, expiry_date: date, *, tenant_id: str) -> OptionsChain` | Fetch full chain for an underlying and expiry (calls + puts). |
| `def select_strike(self, chain: OptionsChain, direction: str, delta_target: Decimal) -> OptionsContract` | **Pure selection** helper: deterministic choice from chain (implemented on base as default algorithm **or** strategy-supplied; broker may override if vendor provides delta). |
| `async def place_options_order(self, contract: OptionsContract, side: OrderSide, quantity: Decimal, *, tenant_id: str, account_id: str) -> OrderReceipt` | Place an order for a specific contract; **must** pass `account_id` (options account — ADR 0003). |
| `async def get_options_positions(self, tenant_id: str, account_id: str) -> list[OptionsPosition]` | List open options positions for the **options** account. |

**Note:** `select_strike` may live on **`BrokerAdapter`** as a **default implementation** using `OptionsChain` data only; if a broker provides **Greeks**, the concrete adapter can populate `delta` on each leg for better matching.

**Tenant scoping:** every method takes `tenant_id`; `account_id` is explicit for placement and positions (options account id from settings or DB).

### 2) New platform models (`src/brokers/models.py`)

Add **broker-agnostic** Pydantic models:

- **`OptionsContract`**
  - `underlying: str`
  - `symbol: str` (OCC or broker-normalized option symbol)
  - `strike: Decimal`
  - `expiry: date`
  - `option_type: Literal["call", "put"]`
  - `delta: Decimal | None` (if known)
  - `raw: dict[str, Any]` (tenant-scoped, optional)

- **`OptionsChain`**
  - `underlying: str`
  - `expiry: date`
  - `calls: list[OptionsContract]`
  - `puts: list[OptionsContract]`
  - `as_of: datetime | None`
  - `raw: dict[str, Any]`

- **`OptionsPosition`**
  - `contract: OptionsContract`
  - `quantity: Decimal` (signed: long/short)
  - `avg_cost: Decimal | None`
  - `current_price: Decimal | None`
  - `account_id: str`
  - `tenant_id: str`

These types must **not** embed TradeStation field names as required fields; vendor payloads stay in `raw`.

### 3) Relationship to existing `Order` model

- Short term: **`place_options_order`** uses **`OptionsContract`** + side/qty rather than overloading **`Order.symbol`** with OCC strings — clearer and safer.
- Long term: **`Order`** may gain `options_contract: OptionsContract | None` — optional follow-up ADR to unify receipts.

### 4) TradeStation implementation notes (concrete adapter only)

Implementation lives under **`src/brokers/tradestation/`** (not in shared code):

- **Chain:** Use TradeStation API v3 **market data** resources that return option chains or option series for an underlying (exact paths vary by environment — e.g. `GET .../marketdata/options/...` style endpoints). Map JSON rows to **`OptionsContract`** with Greeks if returned.
- **Order:** Map **`OptionsContract.symbol`** to the broker’s order symbol field; include **account id** in request body consistent with equity order placement.
- **Positions:** Use **brokerage account positions** filtered to **options** asset class when the API supports filtering; otherwise filter client-side by symbol/OCC pattern.

**Security:** tokens and account ids must remain **tenant-scoped**; never log full chain responses in production at DEBUG without redaction.

## Alternatives considered

| Alternative | Why not chosen |
|-------------|----------------|
| Put OCC strings only in `Order.symbol` | Error-prone; weak typing for strikes/expiry. |
| Use third-party options data only | Adds vendor + licensing; broker still needed for execution. |
| Single `get_chain` returning raw JSON | Violates “no vendor shapes in shared code”. |

## Integration points

- **`BrokerAdapter`** — extended surface for options.
- **`AccountRouter`** — `InstrumentType.OPTIONS` / `FUTURES_OPTIONS` → correct `account_id` before **`place_options_order`** (same as equity orders ADR 0003).
- **`OrderRouter`** — may delegate to **`place_options_order`** when signal carries an **`OptionsContract`**.
- **`ExecutionLogger`** — log contract snapshots (hashed/redacted as needed).

## Consequences

- **Positive:** Options are first-class, testable domain objects.
- **Positive:** Clear seam for IBKR/Alpaca later (different chain endpoints, same models).
- **Negative:** Adapter surface area grows; need capability detection for brokers without options.

## Follow-ups (Tech Lead)

- Implement models + abstract methods on `BrokerAdapter` (or mixin protocol).
- TradeStation adapter: integration tests with mocked HTTP JSON.
- Document OCC normalization rules in broker package README (not in shared models).

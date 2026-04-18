## Tenant scoping guardrails (Phase 1)

**Goal:** make accidental cross-tenant reads/writes harder by default.

### Rules

- **Every tenant-owned table has `tenant_id NOT NULL`** and an index on `tenant_id`.
- Repository/query helpers must **require** `tenant_id` (and `trading_mode` where applicable).
- Avoid generic helpers like `get_by_id(id)` unless they also require `tenant_id`.

### Recommended pattern

Use `db.session.tenant_scoped_query(...)` for tables that include `tenant_id` + `trading_mode`.

For tables that are tenant-owned but do not include `trading_mode`, use explicit filters:

```python
from sqlalchemy import select
from db.models import Strategy

stmt = select(Strategy).where(
    Strategy.owner_kind == "tenant",
    Strategy.owner_tenant_id == tenant_id,
)
```

### Future hardening (Postgres)

Enable Row Level Security (RLS) with policies that enforce:

- `tenant_id = current_setting('app.tenant_id')`

and set `SET LOCAL app.tenant_id = '<tenant_id>'` per request/transaction.


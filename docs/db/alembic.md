## Alembic migrations

This repo uses Alembic to manage schema migrations.

### Run migrations

- **Upgrade to latest**:

```bash
alembic upgrade head
```

### Notes

- The connection string is read from `DATABASE_URL` via `src/config.py`.
- `alembic.ini` intentionally does **not** contain a real connection string to avoid accidental leakage.


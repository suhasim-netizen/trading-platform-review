# Local setup (paper trading)

## Database initialization

Create your `.env` (see `.env.example`) and ensure `DATABASE_URL` points at a writable database.

Run migrations or create tables (Phase 2 runner will call `init_db()` automatically for SQLite/local use).

## Seed platform strategies (required)

The execution runner expects approved platform strategies to exist in the database `strategies` table.

Authoritative definitions live under `docs/strategies/*.md` (YAML frontmatter). The seed script reads those files and upserts rows.

Seed them once (safe to re-run):

```bash
python scripts/seed_strategies.py
```

If you see:

> Strategy 'strategy_001' not found in strategies table. Run: python scripts/seed_strategies.py

run the seed script above before starting the runner.

## Run the runner (smoke)

```bash
python -m src.execution.runner --tenant director --strategy strategy_001 --mode paper --max-bars 2
```


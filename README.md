# Autonomous AI Trading Platform

Multi-tenant trading platform with broker abstraction (`BrokerAdapter`), tenant-scoped data paths, and a strategy registry. See `docs/folder_structure.md` and ADRs under `docs/adr/` for architecture.

## Adding a new strategy

1. **Quant Analyst** adds a specification file under `docs/strategies/` (Markdown with YAML frontmatter at the top — see existing `strategy_*_v*.md` files).
2. Ensure the frontmatter includes at least: `id`, `name`, `version`, `owner_kind`, `owner_tenant_id`, `code_ref`, `asset_class`, and `status`.
3. Run the seed script from the repository root:

   ```bash
   python scripts/seed_strategies.py
   ```

4. Verify the row exists in the database, for example with PostgreSQL:

   ```bash
   psql "$DATABASE_URL" -c "SELECT id, name, version FROM strategies ORDER BY id;"
   ```

   For SQLite, use `sqlite3` against your DB file with an equivalent `SELECT`.

Orchestrator checklist for Phase 3 is in `docs/agents/phase3-plan.md`.

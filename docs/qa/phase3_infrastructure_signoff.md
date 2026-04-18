# Phase 3 — Infrastructure validation sign-off (pre-runner restart)

**Role:** QA Engineer  
**Date:** 2026-04-16  
**Tenant scope:** `director`  
**Result:** **BLOCKED**

---

## Risk approval read

Read `docs/risk/risk_approval_phase3_strategies.md` (signed Risk Manager 2026-04-16). Approved for paper trading:

- **strategy_002** — Equity Momentum
- **strategy_004** — Equity Swing
- **strategy_006** — Futures Intraday VWAP *(conditionally approved for paper; 60 trading days required)*

---

## STEP 1 — Test suite

Command:

```text
pytest tests/ -v --tb=short
```

Result: **54 passed, 0 failed** (1 warning: Starlette `multipart` PendingDeprecationWarning).

---

## STEP 2 — New infrastructure files (exist + import cleanly)

- `src/execution/scanner.py` (`MultiSymbolScanner`): **OK**
- `src/execution/intraday_manager.py` (`IntradayPositionManager`): **OK**
- `src/strategies/` implementation files present in repo: `base.py`, `registry.py`, `executor.py` (strategy definitions for 002/004/006 are stored in DB per Step 3).

Import check executed:

```text
from src.execution.scanner import MultiSymbolScanner
from src.execution.intraday_manager import IntradayPositionManager
```

Result: **Scanner: OK**, **IntradayManager: OK**

---

## STEP 3 — Strategies 002/004/006 exist in DB

Query:

```sql
SELECT id, name, version FROM strategies
WHERE id IN ('strategy_002','strategy_004','strategy_006');
```

Result: **CONFIRMED**

- `strategy_002` — Equity Momentum — `0.1.0`
- `strategy_004` — Equity Swing Pullback — `0.1.0`
- `strategy_006` — Futures Intraday VWAP — `0.1.0`

---

## STEP 4 — Risk limits enforceable (implementation + tests)

- **Daily loss limits (OrderRouter):** enforced and tested (`tests/unit/execution/test_router.py::test_router_blocks_daily_loss_limit`).
- **Hard-close at 15:55 ET (IntradayPositionManager):** implemented (`close_time` default `"15:55"`) and tested (`tests/unit/execution/test_intraday_manager.py::test_eod_close_triggered_at_1555`).

---

## STEP 5 — Broker credentials validity (token expiry)

Query:

```sql
SELECT tenant_id, trading_mode, broker_name, token_expires_at
FROM broker_credentials;
```

Result: **EXPIRED — re-auth required before runner start**

- `director` / `paper` / `tradestation`: `token_expires_at = 2026-04-16T12:30:30.217834-04:00` (**expired**)

---

## Overall verdict

**BLOCKED** — do not restart the runner until the tenant `director` paper trading broker session is re-authenticated (refresh/reauth) and `token_expires_at` is in the future.

### After fix (once token is valid), runner start command

Start the paper trading runner for the three approved strategies (002, 004, 006) using the platform’s documented multi-strategy runner invocation (or the orchestrator job that starts multiple runners). If the runner supports repeating `--strategy`, the expected form is:

```text
python -m src.execution.runner --tenant director --mode paper --strategy strategy_002 --strategy strategy_004 --strategy strategy_006
```

If the runner only supports one strategy per process, start three processes (one per strategy) under the same tenant + paper mode.


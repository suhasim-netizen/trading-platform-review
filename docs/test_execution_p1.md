# Phase 1 Test Execution Results

Date: 2026-04-15  
Executed by: Tech Lead

## pytest results

Command (single run):

```text
pytest tests/unit/db/test_tenant_scoping.py tests/integration/test_token_isolation.py tests/unit/brokers/test_tradestation_auth.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.2.0, pluggy-1.6.0 -- C:\workspace\ClaudeCode\trading-platform\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\workspace\ClaudeCode\trading-platform
configfile: pytest.ini
plugins: anyio-4.13.0, asyncio-0.24.0
asyncio: mode=Mode.STRICT, default_loop_scope=function
collecting ... collected 7 items

tests/unit/db/test_tenant_scoping.py::test_tenant_scoped_query_never_returns_other_tenant_rows PASSED [ 14%]
tests/integration/test_token_isolation.py::test_two_tenant_token_isolation PASSED [ 28%]
tests/unit/brokers/test_tradestation_auth.py::test_exchange_success PASSED [ 42%]
tests/unit/brokers/test_tradestation_auth.py::test_exchange_401_maps_to_auth_error PASSED [ 57%]
tests/unit/brokers/test_tradestation_auth.py::test_network_error_maps_to_broker_network_error PASSED [ 71%]
tests/unit/brokers/test_tradestation_auth.py::test_malformed_json_maps_to_validation_error PASSED [ 85%]
tests/unit/brokers/test_tradestation_auth.py::test_refresh_success PASSED [100%]

============================== warnings summary ===============================
tests/unit/db/test_tenant_scoping.py::test_tenant_scoped_query_never_returns_other_tenant_rows
  C:\workspace\ClaudeCode\trading-platform\.venv\Lib\site-packages\starlette\formparsers.py:12: PendingDeprecationWarning: Please use `import python_multipart` instead.
    import multipart

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 7 passed, 1 warning in 1.37s =========================
```

Summary: **7 passed**, 1 warning (Starlette `multipart` deprecation), ~1.37s.

## Step 2 — Migration result

### Alembic install and version check

`requirements.txt` already pins `alembic==1.13.1`. Installed into `.venv` with:

```text
pip install alembic==1.13.1
```

Verify (recommended: run from a directory **without** the repo’s local `alembic/` migration folder on `sys.path`, because it can shadow the installed `alembic` package):

```text
cd $env:TEMP
C:\workspace\ClaudeCode\trading-platform\.venv\Scripts\python.exe -c "import alembic; print(alembic.__version__)"
```

Output:

```text
1.13.1
```

### `alembic upgrade head`

Environment (SQLite file under repo root for this run):

```text
$env:DATABASE_URL="sqlite+pysqlite:///./.phase1_alembic.db"
```

Full output:

```text
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_phase1_initial, Phase 1 initial schema (multi-tenant).
```

Exit code: **0** (migration applied cleanly).

## Smoke test result

### Uvicorn

From repository root:

```text
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Server log (excerpt):

```text
INFO:     Started server process [10512]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:57211 - "GET /health HTTP/1.1" 200 OK
```

### Health check (httpx as library — not `python -m httpx`)

```text
python -c "import httpx; r = httpx.get('http://127.0.0.1:8000/health'); print(r.status_code, r.text)"
```

Output:

```text
200 {"status":"ok"}
```

## Overall: PASS

# Security review — Phase 2 (paper trading readiness)

**Scope:** `src/brokers/tradestation/adapter.py`, `src/data/pipeline.py`, `src/data/store.py`  
**Reviewer role:** Security Architect  
**Initial review date:** 2026-04-15  
**Remediation re-verification:** 2026-04-15

---

## ADAPTER (`src/brokers/tradestation/adapter.py`)

| # | Checklist item | Verdict | Evidence / notes |
|---|----------------|---------|------------------|
| A1 | All API calls use paper trading URL (`sim.api.tradestation.com`) | **MET** *(remediation verified)* | When `PAPER_TRADING_MODE` resolves True, `_enforce_paper_sim_hosts` (`adapter.py` ~68–79) requires substring `sim.api.tradestation.com` on both `api_base_url` and `stream_base_url` after defaults/normalization (`__init__` ~178–182). Live hosts (e.g. `https://api.tradestation.com`) raise `ValueError` with an explicit message. Unit test `test_live_url_rejected_in_paper_mode` in `tests/unit/brokers/test_tradestation_auth.py` (~181–188) asserts this. `Settings.paper_trading_mode` is defined in `src/config.py` (~50–56) with alias `PAPER_TRADING_MODE`. |
| A2 | No credentials or tokens in logs or exception bodies | **MET** | *(unchanged from initial review)* |
| A3 | `tenant_id` validated on every method before API call | **MET** | *(unchanged from initial review)* |
| A4 | TradeStation errors mapped to internal exceptions only | **MET** | *(unchanged from initial review)* |

---

## DATA PIPELINE (`src/data/pipeline.py`)

| # | Checklist item | Verdict | Evidence / notes |
|---|----------------|---------|------------------|
| D1 | All Redis keys prefixed with `tenant_id` | **MET** | *(unchanged from initial review)* |
| D2 | No cross-tenant data possible in pub/sub channels | **MET** | *(unchanged from initial review)* |
| D3 | Data quality logs do not expose other tenants' symbols | **MET** | *(unchanged from initial review)* |
| D4 | TimescaleDB writes always include `tenant_id` | **MET** | *(unchanged from initial review)* |

---

## GENERAL

| # | Checklist item | Verdict | Evidence / notes |
|---|----------------|---------|------------------|
| G1 | No secrets in any new file | **MET** | *(unchanged from initial review)* |
| G2 | `.env.example` documents paper sim URLs and the "do not use live hosts for paper" rule | **MET** *(remediation verified)* | `.env.example` (~38–48) includes `PAPER_TRADING_MODE`, example `BROKER_API_BASE_URL` / `BROKER_WS_BASE_URL` pointing at **sim** (`sim.api.tradestation.com`), a **WARNING** block for Phase 2 paper-only use, and commented **LIVE** URLs marked **DO NOT USE until Phase 3 sign-off**. |

---

## Remediation (verified)

Previously failed items **A1** and **G2** were re-verified after Tech Lead changes:

1. **A1** — `PAPER_TRADING_MODE` in `src/config.py`; `TradeStationAdapter` calls `_enforce_paper_sim_hosts` when paper mode is active; `test_live_url_rejected_in_paper_mode` confirms `ValueError` for live REST/WS hosts with `paper_trading_mode=True`.
2. **G2** — `.env.example` Phase 2 section documents sim URLs, live URL examples as **do not use**, and `PAPER_TRADING_MODE`.

---

## Sign-off

**Status:** **Signed** — all checklist items **MET** (including remediated A1 and G2).

**Security Architect:** Security Architect — Phase 2 Track A approved — 2026-04-15

*Remediation verified: paper mode enforcement confirmed in adapter and config.*

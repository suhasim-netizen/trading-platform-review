# Strategies 003 & 005 — Deferred backtests (data volume)

These runs are **queued after** 002, 004, and 006 because they require **large 5-minute (and options) datasets**.

## Strategy 003 — Equity intraday ORB

- **Spec:** `docs/strategies/strategy_003_v0.1.0.md`
- **Universe (8 names):** MU, AMD, RKLB, ASTS, APP, LRCX, CLS, CCJ, PLTR
- **Bars:** 5-minute OHLCV per symbol, **America/New_York**, RTH **09:30–15:55** (flat by 15:55 ET)
- **History:** multi-year 5m per ticker for robust ORB / volume-MA warmup (rolling 20 × 5m bars, including prior sessions)
- **Vendor note:** Yahoo chart API **5m** history is limited to roughly the **last ~60 calendar days**; full history needs **Stooq (API key)**, **broker / Polygon / paid vendor**, or internal historical store

## Strategy 005 — Options intraday directional

- **Spec:** `docs/strategies/strategy_005_v0.1.0.md`
- **Underlyings (5m each):** IREN, CLS, MU, APP, AMD, GEV, TSM, PLTR, LITE, COHR, SNDK, STX, LLY, plus **SPX** index / proxy
- **Additional data:** options chains (strikes/expirations), quotes or mid, **greeks/delta** at entry, session rules (0DTE SPX vs next expiry equities), premium ≤ $500 per trade
- **Why deferred:** same **5m underlying** footprint as 003, **plus** options chain time series — not practical to bulk-download via the same free Yahoo intraday path used for 006 validation

When 5m equity history and options snapshots are pinned (path or API), use the same report template as other strategies: `docs/backtests/backtest_{003|005}_v0.1.0_results.md`.

# Data sources (Backtesting)

## SPY daily CSV (2023-01-01 to 2026-01-01)

- **Local file**: `data/spy_2023_2026.csv`
- **Download source**: `https://stooq.com/q/d/l/?s=spy.us&d1=20230101&d2=20260101&i=d`

### Why local CSV?

- **API reliability**: live HTTP pulls (e.g. Yahoo Finance / yfinance) can be blocked, rate-limited, or return partial/empty data in CI and controlled environments.
- **Reproducibility**: a pinned CSV snapshot makes backtests deterministic and reviewable.
- **Auditability**: the exact dataset used for a backtest can be attached to the report and stored alongside artifacts.

### Phase 3 plan (TradeStation historical data)

- Replace CSV ingestion with the platform’s authorised historical market data store sourced from TradeStation.
- Maintain the same backtest interface, but swap the data backend to a tenant-scoped, broker-agnostic historical feed.


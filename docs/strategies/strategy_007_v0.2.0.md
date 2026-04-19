---
id: strategy_007
name: Equity Gap Fade
version: 0.2.0
owner_kind: platform
owner_tenant_id: director
code_ref: src.strategies.gap_fade
asset_class: equity
status: paper
bar_interval: 15m
allocated_capital_usd: 20000
equity_account: SIM3236523M
instruments:
  - TSLA
  - MSFT
  - AAPL
  - AMZN
  - META
  - NFLX
  - HOOD
  - QQQ
  - INTC
  - QCOM
  - PLTR
  - ZS
  - SHOP
  - UBER
  - GOOGL
---

# Strategy 007 — Gap Fade (live paper config)

Approved parameters: gap 0.75–2.0%, VIX 15–20, short-only, 11:00 ET time stop, fifteen-symbol US equity/ETF universe (see frontmatter ``instruments``).

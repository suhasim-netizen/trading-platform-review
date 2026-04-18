"""Seed TradeStation paper accounts (equity + futures) for a tenant.

Usage:
  python scripts/seed_accounts.py
  python scripts/seed_accounts.py --tenant director --mode paper
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from services.paper_accounts_seed import seed_paper_accounts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Seed accounts table from TS_* env account ids.")
    p.add_argument("--tenant", default="director", help="tenant_id (default: director)")
    p.add_argument("--mode", default="paper", choices=["paper", "live"], help="trading_mode")
    args = p.parse_args(argv)
    seed_paper_accounts(args.tenant, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

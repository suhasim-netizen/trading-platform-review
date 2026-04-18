"""Seed platform strategies from ``docs/strategies/*.md`` (YAML frontmatter upsert).

Usage:
  python scripts/seed_strategies.py

Each strategy spec must begin with YAML frontmatter (see docs/strategies/*.md).
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Ensure ``src/`` is importable when running from repo root.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from db.models import Strategy, Tenant  # noqa: E402
from db.session import get_session_factory, init_db  # noqa: E402

_SPECS_DIR = _ROOT / "docs" / "strategies"

_REQUIRED_KEYS = (
    "id",
    "name",
    "version",
    "owner_kind",
    "owner_tenant_id",
    "code_ref",
    "asset_class",
    "status",
)


def _parse_frontmatter(md_path: Path) -> dict[str, Any]:
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n", text, flags=re.DOTALL)
    if not m:
        raise ValueError(f"{md_path}: missing YAML frontmatter (expected --- ... --- at top)")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        raise ValueError(f"{md_path}: frontmatter must parse to a mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in data or data[k] in (None, "")]
    if missing:
        raise ValueError(f"{md_path}: frontmatter missing keys: {', '.join(missing)}")
    return data


def _load_specs() -> list[dict[str, Any]]:
    paths = sorted(_SPECS_DIR.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No .md files under {_SPECS_DIR}")
    return [_parse_frontmatter(p) for p in paths]


def _strategy_sort_key(spec: dict[str, Any]) -> tuple[int, str]:
    sid = spec["id"]
    if sid.startswith("strategy_"):
        try:
            return (int(sid.split("_", 1)[1]), sid)
        except ValueError:
            pass
    return (9999, sid)


def _ensure_tenant(session: Any, tenant_id: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(Tenant(tenant_id=tenant_id, display_name=tenant_id, status="active"))


def seed() -> int:
    init_db()
    specs = sorted(_load_specs(), key=_strategy_sort_key)
    now = datetime.now(UTC)
    factory = get_session_factory()

    with factory() as session:
        for tid in sorted({s["owner_tenant_id"] for s in specs}):
            _ensure_tenant(session, tid)
        for spec in specs:
            sid = spec["id"]
            row = session.get(Strategy, sid)
            if row is None:
                session.add(
                    Strategy(
                        id=sid,
                        owner_kind=spec["owner_kind"],
                        owner_tenant_id=spec["owner_tenant_id"],
                        name=spec["name"],
                        code_ref=spec["code_ref"],
                        version=str(spec["version"]),
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.owner_kind = spec["owner_kind"]
                row.owner_tenant_id = spec["owner_tenant_id"]
                row.name = spec["name"]
                row.code_ref = spec["code_ref"]
                row.version = str(spec["version"])
                row.updated_at = now
        session.commit()

    ids = [s["id"] for s in specs]
    lo, hi = ids[0], ids[-1]
    print(f"Seeded {len(specs)} strategies: {lo} through {hi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(seed())

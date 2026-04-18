from __future__ import annotations

import sys
from pathlib import Path

# Match pytest.ini ``pythonpath = src`` so this script can import app modules when run directly.
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg2

from config import get_settings


@dataclass(frozen=True, slots=True)
class StrategyRow:
    id: str
    name: str
    version: str | None


@dataclass(frozen=True, slots=True)
class CredentialRow:
    tenant_id: str
    trading_mode: str
    broker_name: str
    token_expires_at: datetime | None


def _connect():
    s = get_settings()
    # Do not print the DB URL; it may contain credentials.
    return psycopg2.connect(s.database_url)


def fetch_strategies() -> list[StrategyRow]:
    sql = """
    SELECT id, name, version
    FROM strategies
    WHERE id IN ('strategy_002','strategy_004','strategy_006')
    ORDER BY id;
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return [StrategyRow(id=r[0], name=r[1], version=r[2]) for r in rows]
    finally:
        conn.close()


def fetch_credentials() -> list[CredentialRow]:
    sql = """
    SELECT tenant_id, trading_mode, broker_name, token_expires_at
    FROM broker_credentials
    ORDER BY tenant_id, trading_mode, broker_name;
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return [
            CredentialRow(
                tenant_id=r[0],
                trading_mode=r[1],
                broker_name=r[2],
                token_expires_at=r[3],
            )
            for r in rows
        ]
    finally:
        conn.close()


def main() -> int:
    strategies = fetch_strategies()
    print("strategies_rowcount=", len(strategies))
    for s in strategies:
        print("strategy_row=", (s.id, s.name, s.version))

    creds = fetch_credentials()
    print("credentials_rowcount=", len(creds))
    now = datetime.now(timezone.utc)
    expired: list[tuple[str, str, str, str]] = []
    for c in creds:
        status = "unknown"
        exp = c.token_expires_at
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            status = "expired" if exp <= now else "valid"
            if status == "expired":
                expired.append((c.tenant_id, c.trading_mode, c.broker_name, exp.isoformat()))
        print(
            "credential_row=",
            (
                c.tenant_id,
                c.trading_mode,
                c.broker_name,
                exp.isoformat() if exp else None,
                status,
            ),
        )

    print("expired_count=", len(expired))
    for e in expired:
        print("expired=", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


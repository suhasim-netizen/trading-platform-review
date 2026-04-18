"""OAuth bootstrap helper for TradeStation simulation (paper).

This script:
1) Prints an authorization URL to open in a browser
2) Reads the redirect URL you paste back (extracts ?code=...)
3) Exchanges code for tokens
4) Encrypts and upserts tokens into broker_credentials for tenant_id=director, trading_mode=paper

Never paste secrets into chat logs. This script prints no token values.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text


def _load_env_file() -> None:
    # Load .env if python-dotenv is available; otherwise rely on process env.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def _req(name: str) -> str:
    import os

    v = (os.environ.get(name) or "").strip()
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def _opt(name: str) -> str | None:
    import os

    v = (os.environ.get(name) or "").strip()
    return v or None


def _encrypt(key: str, plain: str) -> str:
    f = Fernet(key.strip().encode("utf-8"))
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def _print_columns(engine) -> None:  # type: ignore[no-untyped-def]
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'broker_credentials' ORDER BY ordinal_position"
                )
            ).fetchall()
            cols = [r[0] for r in rows]
        elif dialect == "sqlite":
            rows = conn.execute(text("PRAGMA table_info('broker_credentials')")).fetchall()
            cols = [r[1] for r in rows]
        else:
            rows = conn.execute(text("SELECT * FROM broker_credentials WHERE 1=0")).keys()
            cols = list(rows)
    print("[DB] broker_credentials columns:", ", ".join(cols))


def main() -> int:
    _load_env_file()

    ts_client_id = _req("TS_CLIENT_ID")
    ts_client_secret = _req("TS_CLIENT_SECRET")
    ts_redirect_uri = _req("TS_REDIRECT_URI")
    token_encryption_key = _req("TOKEN_ENCRYPTION_KEY")
    database_url = _req("DATABASE_URL")

    base = "https://signin.tradestation.com/authorize"
    params = {
        "response_type": "code",
        "client_id": ts_client_id,
        "redirect_uri": ts_redirect_uri,
        "audience": "https://api.tradestation.com",
        "scope": "openid profile offline_access MarketData ReadAccount Trade OptionSpreads Matrix",
    }
    auth_url = f"{base}?{urlencode(params)}"

    print("Open this URL in your browser:")
    print(auth_url)
    print("Log in to TradeStation, then paste the full redirect URL here:")

    redirect_response = input("Paste redirect URL: ").strip()
    try:
        u = urlparse(redirect_response)
        qs = parse_qs(u.query)
        code = (qs.get("code") or [""])[0].strip()
    except Exception:
        code = ""
    if not code:
        raise SystemExit("Could not extract ?code=... from redirect URL")

    token_url = "https://signin.tradestation.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": ts_client_id,
        "client_secret": ts_client_secret,
        "redirect_uri": ts_redirect_uri,
        "code": code,
    }

    try:
        resp = httpx.post(token_url, data=data, headers={"Accept": "application/json"}, timeout=30.0)
    except httpx.RequestError as e:
        raise SystemExit(f"Token exchange network error: {type(e).__name__}") from e

    if resp.status_code >= 400:
        raise SystemExit(f"Token exchange failed: HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as e:
        raise SystemExit("Token exchange response was not valid JSON") from e

    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")

    if not isinstance(access, str) or not access:
        raise SystemExit("Token exchange response missing access_token")
    if refresh is not None and not isinstance(refresh, str):
        refresh = None
    if scope is not None and not isinstance(scope, str):
        scope = None

    expires_at = None
    if expires_in is not None:
        try:
            expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))
        except Exception:
            expires_at = None

    access_ct = _encrypt(token_encryption_key, access)
    refresh_ct = _encrypt(token_encryption_key, refresh) if isinstance(refresh, str) and refresh else None

    engine = create_engine(database_url, future=True)
    _print_columns(engine)

    tenant_id = "director"
    trading_mode = "paper"
    broker_name = "tradestation"
    # OAuth session row key — must stay empty so runner/adapter/store fallbacks match (tenant-wide session).
    OAUTH_ACCOUNT_ID_DEFAULT = ""
    account_id_default = OAUTH_ACCOUNT_ID_DEFAULT

    api_base_url = "https://sim.api.tradestation.com"
    ws_base_url = "wss://sim.api.tradestation.com"

    upsert_sql = text(
        """
        INSERT INTO broker_credentials (
          id, tenant_id, trading_mode, broker_name,
          api_base_url, ws_base_url,
          token_url, client_id,
          access_token_ciphertext, refresh_token_ciphertext,
          token_expires_at, scopes, account_id_default,
          created_at, updated_at
        ) VALUES (
          :id, :tenant_id, :trading_mode, :broker_name,
          :api_base_url, :ws_base_url,
          :token_url, :client_id,
          :access_token_ciphertext, :refresh_token_ciphertext,
          :token_expires_at, :scopes, :account_id_default,
          :created_at, :updated_at
        )
        ON CONFLICT(tenant_id, trading_mode, broker_name, account_id_default) DO UPDATE SET
          access_token_ciphertext = excluded.access_token_ciphertext,
          refresh_token_ciphertext = excluded.refresh_token_ciphertext,
          token_expires_at = excluded.token_expires_at,
          scopes = excluded.scopes,
          updated_at = excluded.updated_at
        """
    )

    import uuid

    now = datetime.now(UTC)
    params_db = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "trading_mode": trading_mode,
        "broker_name": broker_name,
        "api_base_url": api_base_url,
        "ws_base_url": ws_base_url,
        "token_url": token_url,
        "client_id": ts_client_id,
        "access_token_ciphertext": access_ct,
        "refresh_token_ciphertext": refresh_ct,
        "token_expires_at": expires_at,
        "scopes": scope,
        "account_id_default": account_id_default,
        "created_at": now,
        "updated_at": now,
    }

    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            # SQLite uses different upsert syntax; use INSERT OR REPLACE semantics based on unique constraint.
            conn.execute(
                text(
                    """
                    INSERT OR REPLACE INTO broker_credentials (
                      id, tenant_id, trading_mode, broker_name,
                      api_base_url, ws_base_url,
                      token_url, client_id,
                      access_token_ciphertext, refresh_token_ciphertext,
                      token_expires_at, scopes, account_id_default,
                      created_at, updated_at
                    ) VALUES (
                      :id, :tenant_id, :trading_mode, :broker_name,
                      :api_base_url, :ws_base_url,
                      :token_url, :client_id,
                      :access_token_ciphertext, :refresh_token_ciphertext,
                      :token_expires_at, :scopes, :account_id_default,
                      :created_at, :updated_at
                    )
                    """
                ),
                params_db,
            )
        else:
            conn.execute(upsert_sql, params_db)

    print("Token stored successfully. Expires in 20 min.")
    print(
        "Run: python -m src.execution.runner --tenant director --strategy strategy_001 --mode paper --symbol SPY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


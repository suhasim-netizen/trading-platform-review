# DRAFT — Pending Security Architect sign-off (P1-03)

"""TS OAuth helpers (Phase 1 Task 7 draft).

Implements:
- Authorization Code grant exchange
- Refresh Token grant exchange

Constraints:
- No token/secret values in logs or exception messages.
- Map failures to broker-agnostic exception types.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from brokers.exceptions import (
    BrokerAuthError,
    BrokerNetworkError,
    BrokerRateLimitError,
    BrokerValidationError,
)
from brokers.models import AuthToken


_DEFAULT_TOKEN_URL = "https://signin.tradestation.com/oauth/token"


def _parse_token_payload(*, payload: dict[str, Any], tenant_id: str) -> AuthToken:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise BrokerValidationError("token response missing access_token")

    refresh = payload.get("refresh_token")
    if refresh is not None and not isinstance(refresh, str):
        refresh = None

    token_type = payload.get("token_type") if isinstance(payload.get("token_type"), str) else "Bearer"
    scope = payload.get("scope") if isinstance(payload.get("scope"), str) else None

    expires_at = None
    expires_in = payload.get("expires_in")
    if expires_in is not None:
        try:
            expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))
        except Exception:
            # Ignore bad expires_in; treat as unknown expiry.
            expires_at = None

    return AuthToken(
        tenant_id=tenant_id,
        access_token=access,
        refresh_token=refresh,
        token_type=token_type,
        expires_at=expires_at,
        scope=scope,
    )


def _map_http_error(status_code: int) -> Exception:
    if status_code in (400, 401, 403):
        return BrokerAuthError("oauth request rejected")
    if status_code == 429:
        return BrokerRateLimitError("oauth rate limited")
    return BrokerAuthError("oauth request failed")


async def exchange_authorization_code(
    *,
    tenant_id: str,
    authorization_code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    token_url: str | None = None,
    timeout_s: float = 30.0,
) -> AuthToken:
    """Authorization-code exchange for an access token (draft)."""
    url = (token_url or _DEFAULT_TOKEN_URL).strip()
    if not url:
        raise BrokerValidationError("token_url is required")

    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.RequestError as e:
        raise BrokerNetworkError("oauth network error") from e

    if resp.status_code >= 400:
        raise _map_http_error(resp.status_code)

    try:
        payload = resp.json()
    except ValueError as e:
        raise BrokerValidationError("token response not valid json") from e

    if not isinstance(payload, dict):
        raise BrokerValidationError("token response has unexpected shape")

    return _parse_token_payload(payload=payload, tenant_id=tenant_id)


async def refresh_access_token(
    *,
    tenant_id: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    token_url: str | None = None,
    timeout_s: float = 30.0,
) -> AuthToken:
    """Refresh-token exchange for a new access token (draft)."""
    url = (token_url or _DEFAULT_TOKEN_URL).strip()
    if not url:
        raise BrokerValidationError("token_url is required")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.RequestError as e:
        raise BrokerNetworkError("oauth network error") from e

    if resp.status_code >= 400:
        raise _map_http_error(resp.status_code)

    try:
        payload = resp.json()
    except ValueError as e:
        raise BrokerValidationError("token response not valid json") from e

    if not isinstance(payload, dict):
        raise BrokerValidationError("token response has unexpected shape")

    return _parse_token_payload(payload=payload, tenant_id=tenant_id)


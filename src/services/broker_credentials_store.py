# DRAFT — Pending Security Architect sign-off (P1-03)

"""Encrypted broker token persistence (draft).

Tokens are stored encrypted at rest using `security.crypto.encrypt_secret`.
All reads/writes are scoped by:
- tenant_id
- trading_mode
- broker_name
- account_id (may be empty string for "default"/unknown at auth time)

Decryption should occur only in adapter/auth layers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from brokers.exceptions import BrokerAuthError
from brokers.models import AuthToken
from db.models import BrokerCredential
from security.crypto import decrypt_secret, encrypt_secret


class BrokerCredentialsStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_tokens(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        broker_name: str,
        account_id: str,
        token: AuthToken,
    ) -> None:
        stmt = select(BrokerCredential).where(
            BrokerCredential.tenant_id == tenant_id,
            BrokerCredential.trading_mode == trading_mode,
            BrokerCredential.broker_name == broker_name,
            BrokerCredential.account_id_default == account_id,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = BrokerCredential(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                broker_name=broker_name,
                api_base_url="",
                ws_base_url="",
                account_id_default=account_id,
            )
            self._session.add(row)

        row.access_token_ciphertext = encrypt_secret(token.access_token)
        if token.refresh_token:
            row.refresh_token_ciphertext = encrypt_secret(token.refresh_token)
        row.token_expires_at = token.expires_at
        row.scopes = token.scope
        row.updated_at = datetime.now()  # timezone-aware handled by DB default in prod migrations
        # Do not close an enclosing transaction context manager.
        if self._session.in_transaction():
            self._session.flush()
        else:
            self._session.commit()

    def get_refresh_token_ciphertext(
        self, *, tenant_id: str, trading_mode: str, broker_name: str, account_id: str
    ) -> str | None:
        stmt = select(BrokerCredential.refresh_token_ciphertext).where(
            BrokerCredential.tenant_id == tenant_id,
            BrokerCredential.trading_mode == trading_mode,
            BrokerCredential.broker_name == broker_name,
            BrokerCredential.account_id_default == account_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _row_has_access_token(row: BrokerCredential | None) -> bool:
        return bool(row and row.access_token_ciphertext)

    def _select_credential_row(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        broker_name: str,
        account_id: str,
    ) -> BrokerCredential | None:
        stmt = select(BrokerCredential).where(
            BrokerCredential.tenant_id == tenant_id,
            BrokerCredential.trading_mode == trading_mode,
            BrokerCredential.broker_name == broker_name,
            BrokerCredential.account_id_default == account_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def _select_any_credential_row_with_access(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        broker_name: str,
    ) -> BrokerCredential | None:
        """Last resort: tenant/mode/broker row with tokens (handles mis-set ``account_id_default``)."""
        stmt = (
            select(BrokerCredential)
            .where(
                BrokerCredential.tenant_id == tenant_id,
                BrokerCredential.trading_mode == trading_mode,
                BrokerCredential.broker_name == broker_name,
                BrokerCredential.access_token_ciphertext.isnot(None),
            )
            .order_by(desc(BrokerCredential.updated_at))
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_auth_token(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        broker_name: str,
        account_id: str,
    ) -> AuthToken:
        """Load decrypted session tokens for API calls (never log return values).

        Lookup order:

        1. Row matching ``account_id`` (``account_id_default`` in DB).
        2. If missing or no access token, retry with ``account_id_default == ""`` (OAuth bootstrap key).
        3. If still missing, any row for this tenant/mode/broker that has an access token (newest first).

        Raises ``BrokerAuthError`` if no usable session exists.
        """
        row = self._select_credential_row(
            tenant_id=tenant_id,
            trading_mode=trading_mode,
            broker_name=broker_name,
            account_id=account_id,
        )
        if not self._row_has_access_token(row) and account_id != "":
            row = self._select_credential_row(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                broker_name=broker_name,
                account_id="",
            )
        if not self._row_has_access_token(row):
            row = self._select_any_credential_row_with_access(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                broker_name=broker_name,
            )
        if row is None or not row.access_token_ciphertext:
            raise BrokerAuthError("no broker session for tenant")
        access = decrypt_secret(row.access_token_ciphertext)
        refresh = decrypt_secret(row.refresh_token_ciphertext) if row.refresh_token_ciphertext else None
        return AuthToken(
            tenant_id=tenant_id,
            access_token=access,
            refresh_token=refresh,
            expires_at=row.token_expires_at,
            scope=row.scopes,
        )




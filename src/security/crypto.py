"""Fernet helpers for at-rest broker secrets (per Security Architect key rotation policy)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from config import get_settings


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key.strip().encode("utf-8")
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


"""Field-level encryption for client PII using Fernet (AES-128-CBC + HMAC)."""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from backend.config import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = get_settings().ENCRYPTION_KEY
    if not key:
        logger.warning("ENCRYPTION_KEY not set — PII stored unencrypted")
        return None
    _fernet = Fernet(key.encode("utf-8"))
    return _fernet


def encrypt_pii(value: str | None) -> str | None:
    """Encrypt a plaintext PII value. Returns base64 ciphertext or plaintext if no key."""
    if value is None:
        return None
    f = _get_fernet()
    if f is None:
        return value
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_pii(value: str | None) -> str | None:
    """Decrypt a ciphertext PII value. Returns plaintext or passes through if not encrypted."""
    if value is None:
        return None
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value


def is_encryption_enabled() -> bool:
    return _get_fernet() is not None

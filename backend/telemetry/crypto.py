from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from .config import get_settings


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache()
def _get_fernet() -> Fernet:
    settings = get_settings()
    if not settings.credential_secret_key or settings.credential_secret_key == "CHANGE_ME":
        raise RuntimeError(
            "TELEMETRY_CREDENTIAL_SECRET_KEY must be set to a non-default value for credential storage"
        )
    return Fernet(_derive_key(settings.credential_secret_key))


def encrypt_secret(value: str) -> str:
    if value is None:
        raise ValueError("Secret value cannot be None")
    token = _get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(token: str) -> str:
    if not token:
        raise ValueError("Encrypted token is required")
    data = _get_fernet().decrypt(token.encode("utf-8"))
    return data.decode("utf-8")

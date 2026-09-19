"""Encrypt users' model keys at rest, with a key derived from the server's APP_SECRET."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    secret = os.environ.get("APP_SECRET", "")
    if len(secret) < 16:
        raise RuntimeError("Set APP_SECRET (at least 16 characters) to store model keys.")
    key = base64.urlsafe_b64encode(hashlib.sha256(("tailortex-model-key:" + secret).encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None  # APP_SECRET changed: the user re-enters the key


def hint(value: str) -> str:
    """The last four characters, so a user can recognize which key is saved."""
    return "…" + value[-4:] if len(value) >= 8 else "…"

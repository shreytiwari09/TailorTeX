"""Encrypt users' model keys at rest, with a key derived from the server's APP_SECRET."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken


def _secret() -> str:
    """APP_SECRET if set. Otherwise a random secret created on first use and kept in the data folder
    (the Docker volume), so a fresh install works with no configuration. Set APP_SECRET for hosted
    deployments where that folder doesn't persist, otherwise saved keys must be re-entered after a redeploy."""
    secret = os.environ.get("APP_SECRET", "").strip()
    if secret:
        if len(secret) < 16:
            raise RuntimeError("APP_SECRET must be at least 16 characters.")
        return secret
    from ..learn.store import data_dir

    file = data_dir() / "app_secret"
    if file.exists():
        return file.read_text().strip()
    secret = secrets.token_urlsafe(48)
    file.write_text(secret)
    file.chmod(0o600)
    return secret


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("tailortex-model-key:" + _secret()).encode()).digest())
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

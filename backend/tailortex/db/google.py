"""Verify "Sign in with Google" ID tokens against Google's public keys."""

from __future__ import annotations

import asyncio
import os

import jwt
from jwt import PyJWKClient

GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_jwks: PyJWKClient | None = None


class GoogleAuthError(Exception):
    pass


def client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip() or None


def _keys() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(GOOGLE_CERTS, cache_keys=True, lifespan=3600)
    return _jwks


def verify_sync(credential: str) -> dict:
    audience = client_id()
    if not audience:
        raise GoogleAuthError("Google sign-in isn't set up on this server.")
    try:
        signing_key = _keys().get_signing_key_from_jwt(credential)
        claims = jwt.decode(credential, signing_key.key, algorithms=["RS256"], audience=audience, options={"require": ["exp", "iss", "sub", "aud"]})
    except jwt.PyJWTError as e:
        raise GoogleAuthError(f"Google sign-in failed ({e}).") from None
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("Google sign-in failed (wrong issuer).")
    if not claims.get("email") or not claims.get("email_verified"):
        raise GoogleAuthError("Your Google account's email isn't verified.")
    return claims


async def verify(credential: str) -> dict:
    return await asyncio.to_thread(verify_sync, credential)

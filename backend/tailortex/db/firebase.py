"""Verify Firebase Authentication ID tokens.

The browser signs in with Firebase (Google, or an email link) and sends the ID token here. A token is
accepted only if it is signed by Google's securetoken keys, was issued for this Firebase project, and hasn't
expired. No service-account key is needed: verification uses public keys only.
"""

from __future__ import annotations

import asyncio
import os

import jwt
from jwt import PyJWKClient

JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
_jwks: PyJWKClient | None = None


class FirebaseAuthError(Exception):
    pass


def project_id() -> str | None:
    return os.environ.get("FIREBASE_PROJECT_ID", "").strip() or None


def web_config() -> dict | None:
    """The public web config the browser needs to start Firebase. None until it's set up."""
    pid = project_id()
    api_key = os.environ.get("FIREBASE_API_KEY", "").strip()
    if not pid or not api_key:
        return None
    return {
        "apiKey": api_key,
        "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", "").strip() or f"{pid}.firebaseapp.com",
        "projectId": pid,
        "appId": os.environ.get("FIREBASE_APP_ID", "").strip() or None,
    }


def _keys() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks


def verify_sync(id_token: str) -> dict:
    pid = project_id()
    if not pid:
        raise FirebaseAuthError("Sign-in isn't set up on this server.")
    try:
        signing_key = _keys().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token, signing_key.key, algorithms=["RS256"], audience=pid, issuer=f"https://securetoken.google.com/{pid}",
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise FirebaseAuthError(f"Sign-in failed ({e}).") from None
    if not claims.get("sub") or len(str(claims["sub"])) > 128:
        raise FirebaseAuthError("Sign-in failed (bad subject).")
    if not claims.get("email"):
        raise FirebaseAuthError("Your account has no email address.")
    if not claims.get("email_verified"):
        raise FirebaseAuthError("Verify your email address first.")
    return claims


async def verify(id_token: str) -> dict:
    return await asyncio.to_thread(verify_sync, id_token)

"""Fetch and cache a provider's public signing keys (a JWKS document) for verifying ID tokens.

PyJWT's own client downloads with urllib, which uses the operating system's certificate store and fails on
some installs (python.org builds on macOS ship without one). httpx uses the bundled certifi store everywhere.
"""

from __future__ import annotations

import threading
import time

import httpx
import jwt

_REFRESH_AFTER = 3600  # seconds a fetched set is trusted
_MIN_GAP = 60  # an unknown key ID can trigger a refetch at most this often, so junk tokens can't make us hammer the provider


class KeySet:
    def __init__(self, url: str):
        self.url = url
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched = 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> None:
        try:
            res = httpx.get(self.url, timeout=10, follow_redirects=True)
            res.raise_for_status()
            found = {k["kid"]: jwt.PyJWK(k) for k in res.json().get("keys", []) if k.get("kid")}
        except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWTError) as e:
            raise jwt.PyJWKClientError(f"couldn't fetch the provider's signing keys ({e.__class__.__name__})") from None
        self._keys, self._fetched = found, time.monotonic()

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        kid = jwt.get_unverified_header(token).get("kid")
        with self._lock:
            age = time.monotonic() - self._fetched
            if not self._keys or age > _REFRESH_AFTER or (kid not in self._keys and age > _MIN_GAP):
                self._fetch()
            key = self._keys.get(kid or "")
        if key is None:
            raise jwt.PyJWKClientError("no signing key matches this token")
        return key

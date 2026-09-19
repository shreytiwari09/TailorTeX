"""Embeddings: numeric fingerprints of meaning, so similar things can be found even with different words.

A small model (BAAI/bge-small-en-v1.5, 384 numbers per text) runs on the server, so this works whatever
model provider the user brings. If it isn't installed, a hashed bag of canonical terms stands in: it knows
synonyms (K8s = Kubernetes) but not meaning.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import threading

from ..ats.terms import canonical
from .models import EMBEDDING_DIMS

MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None
_lock = threading.Lock()


def _load():
    global _model
    if os.environ.get("TAILORTEX_EMBEDDINGS", "model") != "model":
        return None
    with _lock:
        if _model is None:
            try:
                from fastembed import TextEmbedding

                _model = TextEmbedding(MODEL_NAME)
            except Exception:  # not installed or couldn't download: use the fallback
                _model = False
    return _model or None


def _hashed(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIMS
    for word in re.findall(r"[A-Za-z][A-Za-z0-9+#.]*", text):
        token = canonical(word).lower()
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % EMBEDDING_DIMS] += 1.0 if (h >> 8) % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_sync(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _load()
    if model is None:
        return [_hashed(t) for t in texts]
    return [[float(x) for x in v] for v in model.embed([t[:2000] for t in texts])]


async def embed(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(embed_sync, texts)


def backend_name() -> str:
    return MODEL_NAME if _load() is not None else "hashed terms"

"""A tiny JSON file store for learning data (no database needed for a local MVP)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def data_dir() -> Path:
    d = Path(os.environ.get("TAILORTEX_DATA_DIR", "data"))
    if not d.is_absolute():
        d = Path(__file__).resolve().parents[3] / d
    d.mkdir(parents=True, exist_ok=True)
    return d


class JsonStore:
    def __init__(self, name: str, directory: Path | None = None):
        self.path = (directory or data_dir()) / name

    def load(self) -> dict[str, Any]:
        with _lock:
            if not self.path.exists():
                return {}
            try:
                return json.loads(self.path.read_text())
            except (OSError, ValueError):
                return {}

    def save(self, data: dict[str, Any]) -> None:
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            os.replace(tmp, self.path)

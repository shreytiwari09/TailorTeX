"""Per-user style memory: bullets the user kept or wrote, plus distilled style rules.

Both go into later prompts, so tailoring gets more personal without training
anything. Rules are distilled by the user's own model every few edits.
"""

from __future__ import annotations

from pydantic import BaseModel

from .store import JsonStore

MAX_LIKED = 8
MAX_RULES = 8
DISTILL_EVERY = 5


class StyleRules(BaseModel):
    rules: list[str] = []


class StyleMemory:
    def __init__(self, store: JsonStore | None = None):
        self.store = store or JsonStore("style.json")

    def get(self, user: str | None) -> tuple[list[str], list[str]]:
        """(rules, liked bullets) for a user."""
        if not user:
            return [], []
        u = self.store.load().get(user, {})
        return u.get("rules", [])[:MAX_RULES], u.get("liked", [])[-MAX_LIKED:]

    def record(self, user: str, kept: list[str], edits: list[tuple[str, str]]) -> bool:
        """Remember kept and user-edited bullets. Returns True when it's time to distill rules."""
        data = self.store.load()
        u = data.setdefault(user, {"rules": [], "liked": [], "pairs": [], "events": 0})
        for text in kept + [after for _, after in edits]:
            if text and text not in u["liked"]:
                u["liked"].append(text)
        u["liked"] = u["liked"][-MAX_LIKED:]
        u["pairs"] = (u.get("pairs", []) + [[b, a] for b, a in edits])[-20:]
        before = u.get("events", 0)
        u["events"] = before + len(kept) + len(edits)
        self.store.save(data)
        return bool(edits) and u["events"] // DISTILL_EVERY > before // DISTILL_EVERY

    def pairs(self, user: str) -> list[tuple[str, str]]:
        return [tuple(p) for p in self.store.load().get(user, {}).get("pairs", [])]

    def set_rules(self, user: str, rules: list[str]) -> None:
        data = self.store.load()
        u = data.setdefault(user, {"rules": [], "liked": [], "pairs": [], "events": 0})
        u["rules"] = [r.strip() for r in rules if r.strip()][:MAX_RULES]
        self.store.save(data)

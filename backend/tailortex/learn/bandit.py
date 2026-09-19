"""Thompson-sampling bandit: learns which strategy works for which kind of job.

With users' own keys we can't retrain the model, so learning happens in our
own layer. Each (role family, seniority) context keeps a Beta posterior per
strategy arm. A global table shared by all users is the prior, capped at the
weight of 20 observations so it can't drown out one user's own results. A
user's own table joins after 5 runs. 10% of choices explore at random.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .arms import ARMS, DEFAULT_ORDER
from .store import JsonStore

PRIOR_CAP = 20.0
USER_MIN_RUNS = 5
EXPLORE = 0.10

_FAMILIES = [
    ("ml", r"machine learning|\bml\b|\bai\b|data scien|deep learning|nlp|computer vision|llm"),
    ("data", r"data (engineer|analyst)|analytics|\bbi\b|etl|warehouse"),
    ("devops", r"devops|\bsre\b|site reliability|platform|infrastructure|cloud engineer"),
    ("mobile", r"mobile|ios|android|flutter|react native"),
    ("frontend", r"front[\s-]?end|\bui\b|web developer"),
    ("fullstack", r"full[\s-]?stack"),
    ("backend", r"back[\s-]?end|api|server|distributed"),
    ("security", r"security|appsec|penetration"),
    ("product", r"product manager|\bpm\b|program manager"),
    ("design", r"designer|\bux\b"),
    ("qa", r"\bqa\b|quality|test engineer|sdet"),
]


def role_family(title: str, hint: str | None = None) -> str:
    if hint and hint in {f for f, _ in _FAMILIES} | {"general", "embedded"}:
        return hint
    t = title.lower()
    for fam, pattern in _FAMILIES:
        if re.search(pattern, t):
            return fam
    return "general"


def seniority_bucket(seniority: str | None, title: str = "") -> str:
    s = f"{seniority or ''} {title}".lower()
    if re.search(r"intern|entry|junior|\bjr\b|new grad|graduate|trainee", s):
        return "junior"
    if re.search(r"senior|\bsr\b|staff|principal|lead|manager|head", s):
        return "senior"
    return "mid"


def context_key(title: str, family_hint: str | None, seniority: str | None) -> str:
    return f"{role_family(title, family_hint)}|{seniority_bucket(seniority, title)}"


@dataclass
class Posterior:
    alpha: float = 1.0
    beta: float = 1.0


class Bandit:
    def __init__(self, store: JsonStore | None = None, rng: random.Random | None = None):
        self.store = store or JsonStore("bandit.json")
        self.rng = rng or random.Random()

    def _table(self, data: dict, scope: str, key: str) -> dict[str, list[float]]:
        return data.setdefault(scope, {}).setdefault(key, {})

    def posteriors(self, ctx: str, user: str | None = None) -> dict[str, Posterior]:
        data = self.store.load()
        glob = data.get("global", {}).get(ctx, {})
        mine = data.get("users", {}).get(user or "", {}).get(ctx, {}) if user else {}
        runs = data.get("user_runs", {}).get(user or "", 0) if user else 0
        out: dict[str, Posterior] = {}
        for arm in ARMS:
            a, b = glob.get(arm, [0.0, 0.0])
            n = a + b
            if n > PRIOR_CAP:  # cap the global prior's weight
                a, b = a * PRIOR_CAP / n, b * PRIOR_CAP / n
            p = Posterior(1.0 + a, 1.0 + b)
            if runs >= USER_MIN_RUNS and arm in mine:
                ua, ub = mine[arm]
                p.alpha += ua
                p.beta += ub
            out[arm] = p
        return out

    def choose(self, ctx: str, n: int = 1, user: str | None = None) -> list[str]:
        """n distinct arms: Thompson samples, with some random exploration."""
        n = max(1, min(n, len(ARMS)))
        post = self.posteriors(ctx, user)
        if all(p.alpha == 1.0 and p.beta == 1.0 for p in post.values()):
            return DEFAULT_ORDER[:n]  # nothing learned yet: start with the sensible default
        samples = {arm: self.rng.betavariate(p.alpha, p.beta) for arm, p in post.items()}
        ranked = sorted(samples, key=samples.get, reverse=True)
        chosen = ranked[:n]
        if self.rng.random() < EXPLORE:
            others = [a for a in ARMS if a not in chosen]
            if others:
                chosen[-1] = self.rng.choice(others)
        return chosen

    def update(self, ctx: str, arm: str, reward: float, user: str | None = None) -> None:
        if arm not in ARMS:
            return
        r = max(0.0, min(1.0, reward))
        data = self.store.load()
        g = self._table(data, "global", ctx)
        a, b = g.get(arm, [0.0, 0.0])
        g[arm] = [a + r, b + (1 - r)]
        if user:
            u = data.setdefault("users", {}).setdefault(user, {}).setdefault(ctx, {})
            a, b = u.get(arm, [0.0, 0.0])
            u[arm] = [a + r, b + (1 - r)]
            runs = data.setdefault("user_runs", {})
            runs[user] = runs.get(user, 0) + 1
        self.store.save(data)

    def forget(self, user: str) -> bool:
        """Remove a user's own statistics. Their past runs stay in the anonymous global table."""
        data = self.store.load()
        found = user in data.get("users", {}) or user in data.get("user_runs", {})
        data.get("users", {}).pop(user, None)
        data.get("user_runs", {}).pop(user, None)
        if found:
            self.store.save(data)
        return found

    def stats(self, ctx: str | None = None) -> dict:
        data = self.store.load().get("global", {})
        out = {}
        for key, arms in data.items():
            if ctx and key != ctx:
                continue
            out[key] = {arm: {"mean": round((1 + a) / (2 + a + b), 3), "n": round(a + b, 2)} for arm, (a, b) in arms.items()}
        return out

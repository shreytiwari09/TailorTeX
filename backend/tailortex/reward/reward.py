"""Reward function: layer 0 of the learning loop.

Scores a finished candidate resume from 0 to 1. Every part except bullet quality
can be checked in code, so the same function can later serve as a verifiable
reward for training.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

WEIGHTS = {
    "must_have": 0.40,
    "nice_to_have": 0.15,
    "title": 0.10,
    "parse_health": 0.15,
    "page_fill": 0.10,
    "bullet_quality": 0.10,
}
STUFFING_PENALTY = 0.05
FULL_PAGE = 0.85  # page fill at or above this gets full credit


@dataclass
class RewardInput:
    valid: bool
    compiled: bool
    pages: int
    page_limit: int
    must_have: float
    nice_to_have: float
    title: float
    parse_health: float
    page_fill: float | None = None  # how full the last page is, 0..1
    bullet_quality: float | None = None  # optional judge score, 0..1
    stuffing: int = 0  # number of stuffing violations


@dataclass
class Reward:
    total: float
    gated: str | None
    parts: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def reward(x: RewardInput) -> Reward:
    if not x.valid:
        return Reward(0.0, "validation failed", {})
    if not x.compiled:
        return Reward(0.0, "did not compile", {})
    fill = 1.0 if x.page_fill is None else min(1.0, x.page_fill / FULL_PAGE)
    parts = {
        "must_have": x.must_have,
        "nice_to_have": x.nice_to_have,
        "title": x.title,
        "parse_health": x.parse_health,
        "page_fill": fill,
        "bullet_quality": 0.5 if x.bullet_quality is None else x.bullet_quality,
    }
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    total -= min(STUFFING_PENALTY, 0.01 * x.stuffing)
    rounded = {k: round(v, 4) for k, v in parts.items()}
    if x.pages > x.page_limit:
        # Halve the score per page over the limit rather than zeroing it. A hard zero made every
        # over-long candidate equally worthless, which is what pushed the page fit into dropping
        # bullets that carried keywords. A steep penalty keeps the ordering: shorter still wins.
        total *= 0.5 ** (x.pages - x.page_limit)
        return Reward(round(max(0.0, min(1.0, total)), 4), f"{x.pages} pages, limit {x.page_limit}", rounded)
    return Reward(round(max(0.0, min(1.0, total)), 4), None, rounded)

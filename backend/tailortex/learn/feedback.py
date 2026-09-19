"""Turn what a user does with each suggested change into a reward.

kept = 1, reverted = 0, regenerated = 0.2, edited = 1 - (share of words changed).
A run's reward is 80% user feedback and 20% the layer-0 score, so the bandit
learns what people actually keep, with the checkable score as a tiebreaker.
"""

from __future__ import annotations

from typing import Literal

Action = Literal["kept", "reverted", "edited", "regenerated"]

FEEDBACK_WEIGHT = 0.8


def word_edit_distance(a: str, b: str) -> float:
    """Word-level Levenshtein distance, normalized to 0..1."""
    x, y = a.split(), b.split()
    if not x and not y:
        return 0.0
    prev = list(range(len(y) + 1))
    for i, wx in enumerate(x, 1):
        cur = [i] + [0] * len(y)
        for j, wy in enumerate(y, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wx.lower() != wy.lower()))
        prev = cur
    return prev[-1] / max(len(x), len(y))


def change_reward(action: Action, suggested: str = "", final: str = "") -> float:
    if action == "kept":
        return 1.0
    if action == "reverted":
        return 0.0
    if action == "regenerated":
        return 0.2
    return max(0.0, 1.0 - word_edit_distance(suggested, final))


def run_reward(change_rewards: list[float], layer0: float) -> float:
    if not change_rewards:
        return layer0
    fb = sum(change_rewards) / len(change_rewards)
    return FEEDBACK_WEIGHT * fb + (1 - FEEDBACK_WEIGHT) * layer0

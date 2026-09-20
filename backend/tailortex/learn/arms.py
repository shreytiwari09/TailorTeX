"""The tailoring strategies (bandit arms) the learning loop chooses between.

Each arm changes the model's instructions, never the rules: every arm's output
goes through the same validators.
"""

from __future__ import annotations

ARMS: dict[str, str] = {
    "light": (
        "Make minimal, high-precision edits. Swap in the job's exact wording where the resume already supports it, "
        "reorder bullets and projects by relevance, and update the skills lines. Rewrite at most a third of the bullets."
    ),
    "balanced": (
        "Rewrite the bullets that relate to this job so they lead with the relevant skill and the result, reorder "
        "bullets and projects by relevance, and update the skills lines and summary. Leave unrelated bullets alone."
    ),
    "bold": (
        "Restructure for this job. Rewrite most bullets in the relevant entries around the job's must-haves, drop the "
        "least relevant bullet in entries with four or more (never the only bullet that mentions a must-have), reorder "
        "projects by relevance, and update the skills lines and summary."
    ),
    "evidence_first": (
        "Close gaps with evidence first. For must-have terms marked EVIDENCE, add bullets from the cited evidence and put "
        "those skills in the skills lines and summary. Then tidy the wording of the most relevant bullets."
    ),
}

DEFAULT_ORDER = ["balanced", "evidence_first", "light", "bold"]

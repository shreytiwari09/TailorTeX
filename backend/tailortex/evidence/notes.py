"""Free-form notes about yourself ("Anything else about you") as evidence.

Each non-empty line becomes one fact, so a model can cite exactly the line that
backs a claim. Lines keep the user's own grouping: a number stays with the
sentence that explains it.
"""

from __future__ import annotations

import re

from ..types import EvidenceItem
from .extract import known_skills

MAX_NOTES_CHARS = 6000
MAX_LINE_CHARS = 1000


def note_lines(notes: str) -> list[str]:
    lines = []
    for line in notes[:MAX_NOTES_CHARS].splitlines():
        line = re.sub(r"^\s*(?:[-*•·]|\d+[.)])\s*", "", line).strip()
        if line:
            lines.append(line[:MAX_LINE_CHARS])
    return lines


def notes_to_evidence(notes: str) -> list[EvidenceItem]:
    return [
        EvidenceItem(id=f"n{i}", source="fact", title=(line if len(line) <= 60 else line[:58].rstrip() + "…"), text=line, skills=known_skills(line))
        for i, line in enumerate(note_lines(notes), 1)
    ]

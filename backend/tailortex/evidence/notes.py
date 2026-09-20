"""Free-form notes about yourself ("Anything else about you") as evidence.

A blank line starts a new entry. Everything between blank lines stays together, so a pasted
LinkedIn post, a paragraph about a project, or a list of related lines is one piece of context
rather than a pile of fragments that mean nothing on their own.
"""

from __future__ import annotations

import re

from ..types import EvidenceItem
from .extract import known_skills

MAX_NOTES_CHARS = 20000
MAX_BLOCK_CHARS = 4000
TITLE_CHARS = 60


def note_blocks(notes: str) -> list[str]:
    """The notes split into entries: blank lines separate them, single newlines don't."""
    blocks = []
    for block in re.split(r"\n\s*\n+", notes[:MAX_NOTES_CHARS]):
        lines = []
        for line in block.splitlines():
            line = re.sub(r"^\s*(?:[-*\u2022\u00b7]|\d+[.)])\s*", "", line).strip()
            if line:
                lines.append(line)
        text = "\n".join(lines).strip()
        if text:
            blocks.append(text[:MAX_BLOCK_CHARS])
    return blocks


def block_title(text: str) -> str:
    """A short name for an entry: its first sentence or line, shortened."""
    first = text.strip().splitlines()[0]
    sentence = re.split(r"(?<=[.!?])\s", first)[0].strip() or first
    head = sentence if len(sentence) <= TITLE_CHARS else first
    return head if len(head) <= TITLE_CHARS else head[: TITLE_CHARS - 2].rstrip() + "\u2026"


def notes_to_evidence(notes: str) -> list[EvidenceItem]:
    return [
        EvidenceItem(id=f"n{i}", source="fact", title=block_title(block), text=block, skills=known_skills(block))
        for i, block in enumerate(note_blocks(notes), 1)
    ]

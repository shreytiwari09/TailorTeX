"""What the person tells us about a skill the job wants and their resume doesn't show.

The tool won't write a claim nobody supplied. So when a job asks for PyTorch and nothing in the
resume, notes, GitHub or LinkedIn mentions it, the honest move isn't to drop the term silently: it is
to ask. The person's own sentence becomes evidence, and the bullet written from it is checked against
that sentence like any other, so a tool name or a number that isn't in what they said can't appear.

An answer is stored as a `fact`, the one source the validator lets back a bullet in any section
(`skill` evidence may only reach the skills line and summary; `github` and `portfolio` only projects).
Its id is `ans1`, `ans2`, ... so it can't be deleted by a notes save, which only touches `n1`, `n2`, ...
"""

from __future__ import annotations

import re

from ..types import EvidenceItem
from .extract import known_skills

ANSWER_ID = re.compile(r"^ans\d+$")
MAX_ANSWER_CHARS = 4000
MIN_ANSWER_CHARS = 12  # "I know it" isn't something a bullet can be written from


def is_answer(evidence_id: str) -> bool:
    return bool(ANSWER_ID.match(evidence_id))


def answer_to_evidence(term: str, text: str, n: int, project: str | None = None) -> EvidenceItem:
    """The person's words about one requirement, as a fact a bullet may cite.

    The skill they were asked about is added to the item's skills only if their own text mentions it,
    so an answer that never says "PyTorch" doesn't quietly claim it.
    """
    body = text.strip()[:MAX_ANSWER_CHARS]
    skills = known_skills(body)
    return EvidenceItem(
        id=f"ans{n}",
        source="fact",
        title=(f"Project: {project}" if project else f"What you told us about {term}")[:120],
        text=body,
        skills=skills,
    )


def next_answer_number(existing_ids: list[str]) -> int:
    """The next free ansN, given the ids already stored."""
    taken = [int(i[3:]) for i in existing_ids if is_answer(i)]
    return max(taken, default=0) + 1

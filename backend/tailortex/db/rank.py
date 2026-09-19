"""Choose which background items go into the prompt for a job, by meaning (pgvector) and by keyword."""

from __future__ import annotations

import uuid

from ..ats.terms import contains_term, same_term
from ..types import EvidenceItem, JobAnalysis
from .engine import sessions
from .models import Profile
from .repo import rank_items

MAX_ITEMS_IN_PROMPT = 25


def job_query(analysis: JobAnalysis) -> str:
    terms = ", ".join(t.term for t, _ in analysis.terms())
    return f"{analysis.title}. {analysis.summary or ''} Skills: {terms}"


def make_ranker(profile_id: uuid.UUID):
    async def ranker(analysis: JobAnalysis, items: list[EvidenceItem]) -> tuple[list[EvidenceItem], str | None]:
        async with sessions()() as db:
            profile = await db.get(Profile, profile_id)
            if profile is None:
                return items, None
            similarity = dict(await rank_items(db, profile, job_query(analysis)))

        def mentions_job(item: EvidenceItem) -> bool:
            text = item.full_text()
            return any(contains_term(text, t.term) or any(same_term(s, t.term) for s in item.skills) for t, _ in analysis.terms())

        always = [it for it in items if it.source == "skill" or mentions_job(it)]
        always_ids = {it.id for it in always}
        by_meaning = sorted((it for it in items if it.id not in always_ids), key=lambda it: -similarity.get(it.id, 0.0))
        keep = always + by_meaning[: max(0, MAX_ITEMS_IN_PROMPT - len(always))]
        keep.sort(key=lambda it: -similarity.get(it.id, 1.0 if it.source == "skill" else 0.0))

        top = [it for it in keep if it.id in similarity][:3]
        names = ", ".join(f"{(it.title or it.text)[:40]}" for it in top)
        message = f"Using {len(keep)} of {len(items)} items from your background" + (f"; closest to this job: {names}" if names else "")
        return keep, message

    return ranker

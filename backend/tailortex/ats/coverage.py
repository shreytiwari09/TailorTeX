"""Keyword coverage, gap chips and job-title alignment.

Recruiters search an ATS by keyword, and semantic screeners reward terms used
in context. So a keyword used inside a bullet or the summary scores 1, one that
only appears in the Skills list or an entry heading scores 0.6, and a missing
one scores 0. When the compiled PDF's text is available, a keyword that can't be
found in it scores 0 too: if the ATS can't read it, it isn't there.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..latex.parse import ParsedResume
from ..types import EvidenceItem, JobAnalysis
from .terms import contains_term, count_term, same_term

CONTEXT_SCORE = 1.0
LISTED_SCORE = 0.6


@dataclass
class TermCoverage:
    term: str
    weight: int
    must: bool
    in_context: int
    in_listed: int
    status: Literal["context", "listed", "missing"]
    score: float
    in_pdf: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def zones(doc: ParsedResume) -> tuple[str, str]:
    """(context text: bullets and summary, listed text: skills lines and entry headings)."""
    context: list[str] = []
    listed: list[str] = []
    for s in doc.sections:
        for b in s.blocks:
            if b.kind == "summary":
                context.append(b.text)
            else:
                listed.append(f"{b.label or ''}: {b.text}")
        for e in s.entries:
            listed.append(e.heading)
            context.extend(b.text for b in e.bullets)
    clean = lambda parts: "\n".join(p.replace("**", "") for p in parts)  # noqa: E731
    return clean(context), clean(listed)


def term_coverage(doc: ParsedResume, analysis: JobAnalysis, pdf_text: str | None = None) -> list[TermCoverage]:
    context, listed = zones(doc)
    out: list[TermCoverage] = []
    for t, must in analysis.terms():
        c = count_term(context, t.term)
        li = count_term(listed, t.term)
        in_pdf = contains_term(pdf_text, t.term) if pdf_text is not None else None
        if c:
            status, score = "context", CONTEXT_SCORE
        elif li:
            status, score = "listed", LISTED_SCORE
        else:
            status, score = "missing", 0.0
        if in_pdf is False:
            score = 0.0
        out.append(TermCoverage(t.term, t.weight, must, c, li, status, score, in_pdf))
    return out


def coverage_scores(items: list[TermCoverage]) -> tuple[float, float]:
    """(must-have coverage, nice-to-have coverage), each 0..1, weighted by term weight."""

    def score(group: list[TermCoverage]) -> float:
        total = sum(i.weight for i in group)
        return sum(i.weight * i.score for i in group) / total if total else 1.0

    return score([i for i in items if i.must]), score([i for i in items if not i.must])


@dataclass
class Gap:
    term: str
    weight: int
    must: bool
    status: Literal["present", "evidence", "missing"]
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def gap_analysis(doc: ParsedResume, analysis: JobAnalysis, evidence: list[EvidenceItem]) -> list[Gap]:
    """present: already on the resume. evidence: true but not on the resume yet. missing: no proof."""
    resume_text = doc.plain_text()
    gaps: list[Gap] = []
    for t, must in analysis.terms():
        if contains_term(resume_text, t.term):
            gaps.append(Gap(t.term, t.weight, must, "present"))
            continue
        ids = [ev.id for ev in evidence if contains_term(ev.full_text(), t.term) or any(same_term(sk, t.term) for sk in ev.skills)]
        gaps.append(Gap(t.term, t.weight, must, "evidence" if ids else "missing", ids))
    return gaps


# --- job title alignment ------------------------------------------------------

_TITLE_STOP = {
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "i", "ii", "iii", "iv", "v",
    "intern", "internship", "associate", "entry", "level", "mid", "the", "of", "and", "for", "a",
    "an", "remote", "hybrid", "onsite", "contract", "full", "time", "part", "new", "grad",
    "graduate", "early", "career", "at", "in", "with", "to", "team", "head", "chief",
}
_TITLE_SYNONYMS = {
    "developer": "engineer", "programmer": "engineer", "dev": "engineer", "swe": "software engineer",
    "sde": "software engineer", "front-end": "frontend", "back-end": "backend", "full-stack": "fullstack",
    "ml": "machine learning", "ai": "artificial intelligence", "sre": "site reliability engineer",
    "devops": "devops", "qa": "quality assurance", "ui": "user interface", "ux": "user experience",
    "mle": "machine learning engineer",
}


def _title_tokens(text: str) -> list[str]:
    t = text.lower()
    t = re.sub(r"front[\s-]end", "frontend", t)
    t = re.sub(r"back[\s-]end", "backend", t)
    t = re.sub(r"full[\s-]stack", "fullstack", t)
    words = re.findall(r"[a-z0-9+#.]+(?:-[a-z0-9]+)*", t)
    out: list[str] = []
    for w in words:
        w = w.strip(".")
        w = _TITLE_SYNONYMS.get(w, w)
        out.extend(w.split())
    return [w for w in out if w and w not in _TITLE_STOP]


def title_alignment(doc: ParsedResume, target_title: str) -> float:
    """Share of the target title's words found in the resume's titles, summary and header."""
    want = list(dict.fromkeys(_title_tokens(target_title)))
    if not want:
        return 1.0
    have_parts = [doc.header_text]
    for s in doc.sections:
        if s.kind in ("experience", "summary", "projects", "activities"):
            have_parts.extend(e.heading for e in s.entries)
            have_parts.extend(b.text for b in s.blocks if b.kind == "summary")
    have = set(_title_tokens(" ".join(have_parts)))
    return sum(1 for w in want if w in have) / len(want)

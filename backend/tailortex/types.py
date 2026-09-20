"""Shared models: the evidence bank and the analyzed job description."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceItem(BaseModel):
    """A true fact about the candidate that isn't necessarily on the resume yet."""

    id: str
    source: Literal["github", "skill", "fact", "portfolio", "linkedin"] = "fact"
    title: str = ""
    text: str = ""
    skills: list[str] = Field(default_factory=list)
    url: str | None = None
    # For something found in the resume itself: the entry it came from. A skill shown in one job can't be
    # moved into another job's bullets, so such an item can only back bullets in that same entry.
    scope: str | None = None

    def full_text(self) -> str:
        return " ".join(p for p in [self.title, self.text, ", ".join(self.skills)] if p)


class JobTerm(BaseModel):
    term: str
    weight: int = Field(default=2, ge=1, le=3, description="3 = central to the role, 1 = mentioned in passing")

    @field_validator("weight", mode="before")
    @classmethod
    def _clamp(cls, v):
        """Models sometimes answer 0, 5 or "high"; keep it in 1..3."""
        try:
            return max(1, min(3, round(float(v))))
        except (TypeError, ValueError):
            return {"high": 3, "medium": 2, "low": 1}.get(str(v).strip().lower(), 2)


class JobAnalysis(BaseModel):
    title: str = ""
    company: str | None = None
    seniority: str | None = None
    role_family: str | None = None
    must_have: list[JobTerm] = Field(default_factory=list)
    nice_to_have: list[JobTerm] = Field(default_factory=list)
    summary: str | None = None

    def terms(self) -> list[tuple[JobTerm, bool]]:
        """(term, is_must_have) pairs, must-haves first."""
        return [(t, True) for t in self.must_have] + [(t, False) for t in self.nice_to_have]


class ProjectInfo(BaseModel):
    """A project the person did that isn't on the resume. They say what it is; TailorTeX writes the LaTeX."""

    name: str = Field(min_length=2, max_length=120)
    dates: str = Field(default="", max_length=40, description="For example: Jan 2026 - Apr 2026")
    tech: list[str] = Field(default_factory=list, max_length=12)


class Answer(BaseModel):
    """The person's own words about a skill the job asks for and nothing shows they have."""

    term: str = Field(max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    target: str | None = Field(default=None, max_length=40, description="The entry they say it belongs to, or None to let the model choose")
    project: ProjectInfo | None = Field(default=None, description="Set when this was a separate project: it becomes code to paste into Projects, not a change to an entry")

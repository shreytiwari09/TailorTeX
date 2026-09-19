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

"""What the model is asked to return. Flat and nullable, so every provider handles it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..ops import Op

_OP_ALIASES = {
    "replace": "rewrite", "edit": "rewrite", "update": "rewrite", "modify": "rewrite", "rephrase": "rewrite",
    "insert": "add", "add_bullet": "add", "addbullet": "add", "append": "add", "new": "add",
    "remove": "drop", "delete": "drop", "drop_bullet": "drop",
    "move": "reorder", "reorder_bullets": "reorder", "sort": "reorder",
    "reorder_projects": "reorder_entries", "reorderentries": "reorder_entries",
    "remove_entry": "drop_entry", "delete_entry": "drop_entry", "dropentry": "drop_entry",
}


def clean_id(value: str) -> str:
    """Model replies sometimes wrap IDs in brackets or quotes: "[s1.e0.b2]" -> "s1.e0.b2"."""
    return value.strip().strip("[]()'\"` ").strip()


class PlanOp(BaseModel):
    op: Literal["rewrite", "add", "drop", "reorder", "reorder_entries", "drop_entry"]
    target: str = Field(description="Block ID (rewrite, drop), entry ID (add, reorder, drop_entry) or section ID (reorder_entries)")
    text: str | None = Field(default=None, description="New plain text for rewrite/add; **bold** allowed, never LaTeX")
    after: str | None = Field(default=None, description="For add: the bullet ID to insert after, or null to append")
    order: list[str] | None = Field(default=None, description="For reorder / reorder_entries: every ID in the new order")
    evidence: list[str] | None = Field(default=None, description="Evidence IDs that support new terms or numbers")
    reason: str = Field(default="", description="One short sentence: why this helps for this job")

    @field_validator("op", mode="before")
    @classmethod
    def _normalize_op(cls, v):
        if isinstance(v, str):
            key = v.strip().lower().replace("-", "_").replace(" ", "_")
            return _OP_ALIASES.get(key, key)
        return v

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v):
        return v or ""

    def to_op(self) -> Op:
        return Op(
            op=self.op, target=clean_id(self.target), text=self.text,
            after=clean_id(self.after) if self.after else None,
            order=[clean_id(x) for x in self.order] if self.order else None,
            evidence=[clean_id(e) for e in (self.evidence or []) if clean_id(e)], reason=self.reason, source="model",
        )


class Plan(BaseModel):
    ops: list[PlanOp] = Field(default_factory=list)


class Followup(BaseModel):
    """A question that would make a too-thin answer usable."""

    term: str
    question: str = Field(description="One short question, such as: What did you build with it, and what changed?")


class ProjectDraft(BaseModel):
    """The bullets for one new project, written from one answer."""

    answer: str = Field(description="The id of the answer these bullets are written from")
    name: str = Field(default="", description="The project's name exactly as the answer gives it, or empty if the answer doesn't name it")
    dates: str = Field(default="", description="When, exactly as the answer says, or empty")
    tech: list[str] = Field(default_factory=list, description="Technologies the answer names")
    bullets: list[str] = Field(default_factory=list, description="Two to four bullets, plain text, **bold** allowed")


class Draft(BaseModel):
    ops: list[PlanOp] = Field(default_factory=list)
    projects: list[ProjectDraft] = Field(default_factory=list)
    followups: list[Followup] = Field(default_factory=list)


class SupportItem(BaseModel):
    term: str
    supported: bool = False
    passage: str = Field(default="", description="The id of the passage that shows it")
    quote: str = Field(default="", description="The exact words from that passage that show it, copied verbatim")
    how: Literal["named", "described"] = Field(default="described", description="named: the passage names it. described: it shows the work in other words")


class SupportReply(BaseModel):
    terms: list[SupportItem] = Field(default_factory=list)


class SkillAdd(BaseModel):
    term: str = Field(description="The skill exactly as the person said it")
    line: str = Field(default="", description="The id of the Skills line it fits best, from the resume outline, or empty")


class ChatTurn(BaseModel):
    """What the model decided a message from the person means, and what to do about it."""

    reply: str = Field(default="", description="One or two plain sentences: what you did, or your one question")
    skills: list[SkillAdd] = Field(default_factory=list, description="Skills the person says they have, to put on a Skills line")
    ops: list[PlanOp] = Field(default_factory=list, description="Bullets to add to entries already on the resume")
    projects: list[ProjectDraft] = Field(default_factory=list, description="Separate projects, not on the resume")
    skipped: list[str] = Field(default_factory=list, description="Job skills the person says they haven't done or want to skip")
    handled: list[str] = Field(default_factory=list, description="Job skills dealt with this turn: added, written up or skipped")
    needs_more: bool = Field(default=False, description="True only if reply is a question you need answered")

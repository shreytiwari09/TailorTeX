"""What the model is asked to return. Flat and nullable, so every provider handles it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..ops import Op


class PlanOp(BaseModel):
    op: Literal["rewrite", "add", "drop", "reorder", "reorder_entries", "drop_entry"]
    target: str = Field(description="Block ID (rewrite, drop), entry ID (add, reorder, drop_entry) or section ID (reorder_entries)")
    text: str | None = Field(default=None, description="New plain text for rewrite/add; **bold** allowed, never LaTeX")
    after: str | None = Field(default=None, description="For add: the bullet ID to insert after, or null to append")
    order: list[str] | None = Field(default=None, description="For reorder / reorder_entries: every ID in the new order")
    evidence: list[str] | None = Field(default=None, description="Evidence IDs that support new terms or numbers")
    reason: str = Field(default="", description="One short sentence: why this helps for this job")

    def to_op(self) -> Op:
        return Op(
            op=self.op, target=self.target.strip(), text=self.text, after=self.after, order=self.order,
            evidence=[e.strip() for e in (self.evidence or [])], reason=self.reason, source="model",
        )


class Plan(BaseModel):
    ops: list[PlanOp] = Field(default_factory=list)

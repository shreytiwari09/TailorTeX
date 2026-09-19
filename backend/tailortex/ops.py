"""Edit operations: the only way a resume changes.

The model returns these instead of a new .tex file. Text is plain text with
**bold** only; the editor turns it into LaTeX with the escaper.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OpKind = Literal["rewrite", "add", "drop", "reorder", "reorder_entries", "drop_entry"]


class Op(BaseModel):
    op: OpKind
    target: str = Field(description="Block ID for rewrite/drop, entry ID for add/reorder/drop_entry, section ID for reorder_entries")
    text: str | None = None
    after: str | None = Field(default=None, description="For add: the bullet ID to insert after; null to append")
    order: list[str] | None = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    source: Literal["model", "fit", "user"] = "model"

    def describe(self) -> str:
        if self.op == "rewrite":
            return f"rewrite {self.target}"
        if self.op == "add":
            return f"add a bullet to {self.target}"
        if self.op == "drop":
            return f"drop {self.target}"
        if self.op == "drop_entry":
            return f"drop entry {self.target}"
        if self.op == "reorder":
            return f"reorder bullets in {self.target}"
        return f"reorder entries in {self.target}"

"""Apply edit operations to the source.

Only the spans an operation touches are rebuilt. Entries whose bullets are
added, dropped or reordered are rebuilt from their bullets, keeping the original
whitespace between them; sections whose entries are reordered are rebuilt from
their entries. Every other byte of the file is copied unchanged.
"""

from __future__ import annotations

from ..ops import Op
from .parse import Block, Entry, ParsedResume, Section
from .text import plain_to_latex

Edit = tuple[int, int, str]


class ApplyError(ValueError):
    pass


def _render(src: str, a: int, b: int, edits: list[Edit]) -> str:
    out: list[str] = []
    pos = a
    for s, e, r in sorted(edits):
        if s < pos:
            raise ApplyError("overlapping edits")
        out.append(src[pos:s])
        out.append(r)
        pos = e
    out.append(src[pos:b])
    return "".join(out)


def _join(src: str, children: list[tuple[int, int]], new_children: list[str]) -> str:
    """Join rebuilt children using the original separators between them."""
    seps = [src[children[i][1] : children[i + 1][0]] for i in range(len(children) - 1)]
    if not seps:
        seps = ["\n" + " " * _indent(src, children[0][0])]
    out = [new_children[0]]
    for i, child in enumerate(new_children[1:]):
        out.append(seps[min(i, len(seps) - 1)])
        out.append(child)
    return "".join(out)


def _indent(src: str, pos: int) -> int:
    line_start = src.rfind("\n", 0, pos) + 1
    return pos - line_start


class _Plan:
    def __init__(self, doc: ParsedResume, ops: list[Op]):
        self.rewrites: dict[str, str] = {}
        self.drops: set[str] = set()
        self.adds: dict[str, list[Op]] = {}
        self.orders: dict[str, list[str]] = {}
        self.entry_orders: dict[str, list[str]] = {}
        self.dropped_entries: set[str] = set()
        for op in ops:
            if op.op == "rewrite":
                if doc.block(op.target) is None:
                    raise ApplyError(f"unknown block {op.target}")
                self.rewrites[op.target] = plain_to_latex(op.text or "")
            elif op.op == "drop":
                if doc.block(op.target) is None:
                    raise ApplyError(f"unknown block {op.target}")
                self.drops.add(op.target)
            elif op.op == "add":
                if doc.entry(op.target) is None:
                    raise ApplyError(f"unknown entry {op.target}")
                self.adds.setdefault(op.target, []).append(op)
            elif op.op == "reorder":
                self.orders[op.target] = list(op.order or [])
            elif op.op == "reorder_entries":
                self.entry_orders[op.target] = list(op.order or [])
            elif op.op == "drop_entry":
                self.dropped_entries.add(op.target)


def _block_edit(src: str, bl: Block, plan: _Plan) -> list[Edit]:
    if bl.id in plan.rewrites:
        return [(bl.text_span[0], bl.text_span[1], plan.rewrites[bl.id])]
    return []


def _render_block(src: str, bl: Block, plan: _Plan) -> str:
    return _render(src, bl.span[0], bl.span[1], _block_edit(src, bl, plan))


def _new_bullet(entry: Entry, doc: ParsedResume, text: str) -> str:
    template = entry.bullets[0] if entry.bullets else None
    latex = plain_to_latex(text)
    if template is not None and template.macro:
        if doc.bullet_macros.get(template.macro, 0) != 0:
            raise ApplyError(f"can't add bullets to entries that use \\{template.macro}")
        return f"\\{template.macro}{{{latex}}}"
    return f"\\item {latex}"


def _entry_edits(src: str, doc: ParsedResume, entry: Entry, plan: _Plan) -> list[Edit]:
    restructured = entry.id in plan.adds or entry.id in plan.orders or any(b.id in plan.drops for b in entry.bullets)
    if not restructured or not entry.bullets:
        return [e for b in entry.bullets for e in _block_edit(src, b, plan)]

    by_id = {b.id: b for b in entry.bullets}
    order = plan.orders.get(entry.id) or [b.id for b in entry.bullets]
    if sorted(order) != sorted(by_id):
        raise ApplyError(f"reorder of {entry.id} must list each of its bullets exactly once")

    sequence: list[str] = []  # rendered bullets
    adds = plan.adds.get(entry.id, [])
    anchored: dict[str | None, list[Op]] = {}
    for op in adds:
        key = op.after if op.after in by_id else None
        anchored.setdefault(key, []).append(op)
    for bid in order:
        if bid not in plan.drops:
            sequence.append(_render_block(src, by_id[bid], plan))
        for op in anchored.get(bid, []):
            sequence.append(_new_bullet(entry, doc, op.text or ""))
    for op in anchored.get(None, []):
        sequence.append(_new_bullet(entry, doc, op.text or ""))

    if not sequence:
        raise ApplyError(f"{entry.id} would have no bullets left; an empty list doesn't compile")
    region = (entry.bullets[0].span[0], entry.bullets[-1].span[1])
    return [(region[0], region[1], _join(src, [b.span for b in entry.bullets], sequence))]


def _section_edits(src: str, doc: ParsedResume, sec: Section, plan: _Plan) -> list[Edit]:
    edits: list[Edit] = []
    for bl in sec.blocks:
        edits.extend(_block_edit(src, bl, plan))

    restructured = sec.id in plan.entry_orders or any(e.id in plan.dropped_entries for e in sec.entries)
    if not restructured:
        for e in sec.entries:
            edits.extend(_entry_edits(src, doc, e, plan))
        return edits

    if not sec.entries_reorderable:
        raise ApplyError(f"entries in {sec.id} can't be reordered or dropped in this template")
    by_id = {e.id: e for e in sec.entries}
    order = plan.entry_orders.get(sec.id) or [e.id for e in sec.entries]
    if sorted(order) != sorted(by_id):
        raise ApplyError(f"reorder of {sec.id} must list each of its entries exactly once")
    rendered = []
    for eid in order:
        if eid in plan.dropped_entries:
            continue
        e = by_id[eid]
        rendered.append(_render(src, e.span[0], e.span[1], _entry_edits(src, doc, e, plan)))
    if not rendered:
        raise ApplyError(f"{sec.id} would have no entries left")
    region = (sec.entries[0].span[0], sec.entries[-1].span[1])
    edits.append((region[0], region[1], _join(src, [e.span for e in sec.entries], rendered)))
    return edits


def apply_ops(doc: ParsedResume, ops: list[Op]) -> str:
    """The new .tex source with the operations applied. No ops gives back the identical file."""
    if not ops:
        return doc.source
    plan = _Plan(doc, ops)
    src = doc.source
    edits: list[Edit] = []
    for sec in doc.sections:
        edits.extend(_section_edits(src, doc, sec, plan))
    return _render(src, 0, len(src), edits)

"""Validators: the code that makes "never invents" true whatever the model does.

Every operation the model proposes is checked here, and rejected operations go
back to the model with a plain-English reason. The rules:

- **Specific terms** (tools, skills, proper nouns, acronyms) in new text must
  already be supported. A bullet may only use terms from its own entry (its
  heading and bullets) or from evidence it cites, so a skill used in one job
  can't be moved into another. The summary and skills lines may use anything on
  the resume or in the evidence bank.
- **Numbers** in a rewritten bullet must come from that bullet, its entry
  heading, or cited evidence. A metric can't be attached to a claim it
  doesn't support.
- **Evidence scope:** confirmed skills ("I can defend X") only go into the
  summary and skills lines; GitHub and portfolio evidence only into projects,
  activities, summary and skills; free-text facts anywhere.
- **Locked** sections and blocks can't change; entries keep at least one bullet.
- **Length:** bullets stay within the template's budget.
- **Keyword stuffing:** no job keyword more than 3 times across bullets and summary.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..ats.coverage import coverage_loss, zones_after
from ..ats.terms import SYNONYM_GROUPS, contains_term, count_term, is_known_tech
from ..latex.parse import Block, ParsedResume
from ..ops import Op
from ..types import EvidenceItem, JobAnalysis

MAX_KEYWORD_USES = 3

GENERIC_OK = {
    "API", "APIs", "SDK", "SDKs", "CLI", "HTTP", "HTTPS", "URL", "URLs", "ID", "IDs", "PR", "PRs",
    "QA", "KPI", "KPIs", "MVP", "CPU", "GPU", "RAM", "OS", "US", "UK", "EU", "CEO", "CTO", "VP",
    "I", "OK", "FAQ", "PDF", "CSV", "PoC", "POC", "ETA", "SLA", "SLAs", "SLO", "SLOs", "B2B", "B2C",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep",
    "Sept", "Oct", "Nov", "Dec", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "twice": 2, "double": 2,
    "doubled": 2, "triple": 3, "tripled": 3, "half": 50, "hundred": 100, "thousand": 1000,
}
_UNITS = {
    "%": ("pct", 1), "percent": ("pct", 1), "x": ("mult", 1), "×": ("mult", 1),
    "k": ("n", 1e3), "K": ("n", 1e3), "m": ("n", 1e6), "M": ("n", 1e6), "mm": ("n", 1e6), "b": ("n", 1e9), "B": ("n", 1e9),
    "million": ("n", 1e6), "billion": ("n", 1e9), "thousand": ("n", 1e3), "lakh": ("n", 1e5), "crore": ("n", 1e7),
    "ms": ("time", 1e-3), "s": ("time", 1), "sec": ("time", 1), "secs": ("time", 1), "seconds": ("time", 1),
    "min": ("time", 60), "mins": ("time", 60), "minutes": ("time", 60), "h": ("time", 3600), "hr": ("time", 3600),
    "hrs": ("time", 3600), "hours": ("time", 3600), "days": ("time", 86400), "weeks": ("time", 604800),
    "kb": ("size", 1e3), "KB": ("size", 1e3), "mb": ("size", 1e6), "MB": ("size", 1e6), "gb": ("size", 1e9),
    "GB": ("size", 1e9), "tb": ("size", 1e12), "TB": ("size", 1e12),
}
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])(\$|₹|€|£|Rs\.?\s?)?(\d[\d,]*(?:\.\d+)?)(\+)?\s?"
    r"(%|×|percent\b|million\b|billion\b|thousand\b|lakh\b|crore\b|ms\b|secs?\b|seconds\b|mins?\b|minutes\b|hrs?\b|hours\b|days\b|weeks\b|[kKmMbB]\b|mm\b|[kKmMgGtT][bB]\b|x\b|s\b|h\b)?"
    r"(?![A-Za-z0-9])"
)


@dataclass
class Violation:
    op_index: int
    op: Op
    rule: str
    message: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["op"] = self.op.model_dump()
        return d


@dataclass
class ValidationResult:
    valid: list[Op]
    violations: list[Violation] = field(default_factory=list)


@dataclass
class ValidationContext:
    doc: ParsedResume
    evidence: list[EvidenceItem]
    analysis: JobAnalysis | None = None
    max_keyword_uses: int = MAX_KEYWORD_USES
    protect_coverage: bool = True  # refuse a drop that removes the last mention of a must-have keyword


def _and(terms: list[str]) -> str:
    """'Kubernetes', or 'Kubernetes and Terraform', or 'Kubernetes, Terraform and Go'."""
    quoted = [f"'{t}'" for t in terms]
    return quoted[0] if len(quoted) == 1 else " and ".join([", ".join(quoted[:-1]), quoted[-1]])


def _coverage_loss(ctx: ValidationContext, valid: list[Op], candidate: Op) -> list[str]:
    """Must-have keywords the resume would stop showing in a bullet if this drop were allowed."""
    if not ctx.protect_coverage or ctx.analysis is None:
        return []
    return coverage_loss(ctx.doc, ctx.analysis, valid, candidate)


# --- extraction ---------------------------------------------------------------


def metrics(text: str, words: bool = True) -> list[tuple[str, float, str]]:
    """(surface form, normalized value, unit class) for every metric-like number in text.

    Number words ("three", "doubled") count too, except "one", which is mostly not a number.
    """
    out = []
    for m in _NUM_RE.finditer(text.replace("**", "")):
        currency, raw, _plus, unit = m.groups()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        cls, mult = _UNITS.get(unit or "", ("n", 1))
        if unit and unit not in _UNITS:
            cls, mult = _UNITS.get(unit.lower(), ("n", 1))
        if currency:
            cls = "money" if cls == "n" else cls
        out.append((m.group(0).strip(), value * mult, cls))
    for w, v in _NUMBER_WORDS.items():
        if not words or w == "one":
            continue
        if re.search(rf"\b{w}\b", text, re.IGNORECASE):
            out.append((w, float(v), "n"))
    return out


def metric_allowed(value: float, cls: str, allowed: list[tuple[str, float, str]]) -> bool:
    for _s, v, c in allowed:
        same_class = c == cls or {c, cls} <= {"n", "money"}
        if same_class and abs(v - value) <= 1e-9 * max(1.0, abs(v)):
            return True
    return False


_TECH_SHAPE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]*(?:[.+#/][A-Za-z0-9+#]+)+|[A-Za-z]+[+#]+|\.[A-Za-z]{2,})")
_ACRONYM = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]*[A-Z](?:s)?(?![A-Za-z0-9])")
_CAMEL = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]*[a-z][A-Z][A-Za-z0-9]*(?![A-Za-z0-9])")
_CAPWORD = re.compile(r"(?<![A-Za-z0-9])[A-Z][a-z][A-Za-z0-9]*(?![A-Za-z0-9])")


def specific_terms(text: str) -> list[str]:
    """Tools, skills, proper nouns and acronyms in text: the things that could be invented."""
    t = text.replace("**", "")
    found: dict[str, None] = {}
    # Known tech names and phrases, in any casing the matcher accepts.
    for group in SYNONYM_GROUPS:
        for v in group:
            if contains_term(t, v):
                found[group[0]] = None
                break
    for rx in (_TECH_SHAPE, _ACRONYM, _CAMEL):
        for m in rx.finditer(t):
            w = m.group(0).rstrip(".")
            if re.fullmatch(r"[\d.,/]+", w):
                continue
            found[w] = None
    # Capitalized words that don't start a sentence.
    for m in _CAPWORD.finditer(t):
        before = t[: m.start()].rstrip()
        if not before or before[-1] in ".!?:;•\n-–—(\"'":
            continue
        found[m.group(0)] = None
    return [w for w in found if w not in GENERIC_OK]


# --- the validator --------------------------------------------------------------


def _entry_corpus(doc: ParsedResume, entry_id: str | None) -> str:
    e = doc.entry(entry_id) if entry_id else None
    if not e:
        return ""
    return "\n".join([e.heading] + [b.text.replace("**", "") for b in e.bullets])


def _evidence_allowed_in(item: EvidenceItem, section_kind: str, block_kind: str) -> bool:
    if block_kind in ("summary", "skills"):
        return True
    if item.source == "skill":
        return False
    if item.source in ("github", "portfolio"):
        return section_kind in ("projects", "activities", "summary")
    return True


def validate_ops(ops: list[Op], ctx: ValidationContext) -> ValidationResult:
    doc = ctx.doc
    ev_by_id = {e.id: e for e in ctx.evidence}
    resume_text = doc.plain_text()
    all_evidence_text = "\n".join(e.full_text() for e in ctx.evidence)
    valid: list[tuple[int, Op]] = []
    violations: list[Violation] = []
    touched: set[str] = set()
    drops_per_entry: dict[str, int] = {}
    dropped_entries: dict[str, int] = {}

    def reject(i: int, op: Op, rule: str, message: str) -> None:
        violations.append(Violation(i, op, rule, message))

    for i, op in enumerate(ops):
        if op.op in ("rewrite", "drop"):
            bl = doc.block(op.target)
            if bl is None:
                reject(i, op, "unknown_target", f"There is no block {op.target}.")
                continue
            if bl.locked:
                reject(i, op, "locked", f"{op.target} is locked ({bl.lock_reason}) and can't be changed.")
                continue
            if op.target in touched:
                reject(i, op, "duplicate", f"{op.target} already has a change; make one change per block.")
                continue
            if op.op == "drop":
                if bl.kind != "bullet":
                    reject(i, op, "structure", f"Only bullets can be dropped; {op.target} is a {bl.kind}.")
                    continue
                entry = doc.entry(bl.entry_id or "")
                n = drops_per_entry.get(bl.entry_id or "", 0) + 1
                if entry and n >= len(entry.bullets):
                    reject(i, op, "structure", f"Dropping {op.target} would leave {entry.id} with no bullets.")
                    continue
                lost = _coverage_loss(ctx, [o for _, o in valid], op)
                if lost:
                    reject(i, op, "coverage", f"Dropping {op.target} would remove the only mention of {_and(lost)}, which this job requires. Rewrite it to make room instead.")
                    continue
                drops_per_entry[bl.entry_id or ""] = n
                touched.add(op.target)
                valid.append((i, op))
                continue
            msg = _check_text(op, bl, doc, ctx, ev_by_id, resume_text, all_evidence_text)
            if msg:
                reject(i, op, msg[0], msg[1])
                continue
            touched.add(op.target)
            valid.append((i, op))
        elif op.op == "add":
            entry = doc.entry(op.target)
            if entry is None:
                reject(i, op, "unknown_target", f"There is no entry {op.target}.")
                continue
            if entry.locked or not entry.bullets or any(b.locked and b.lock_reason == "section is locked" for b in entry.bullets):
                reject(i, op, "locked", f"Bullets can't be added to {op.target}.")
                continue
            if entry.bullets[0].macro and doc.bullet_macros.get(entry.bullets[0].macro, 0) != 0:
                reject(i, op, "structure", f"This template's bullets in {op.target} can't be added to automatically.")
                continue
            probe = Block(id=op.target + ".new", kind="bullet", section_id=entry.section_id, entry_id=entry.id, span=(0, 0), text_span=(0, 0), text="")
            msg = _check_text(op, probe, doc, ctx, ev_by_id, resume_text, all_evidence_text)
            if msg:
                reject(i, op, msg[0], msg[1])
                continue
            valid.append((i, op))
        elif op.op == "reorder":
            entry = doc.entry(op.target)
            if entry is None or entry.locked:
                reject(i, op, "unknown_target" if entry is None else "locked", f"Can't reorder bullets in {op.target}.")
                continue
            ids = [b.id for b in entry.bullets]
            if sorted(op.order or []) != sorted(ids):
                reject(i, op, "structure", f"A reorder of {op.target} must list each of its bullets exactly once: {', '.join(ids)}.")
                continue
            if any(b.locked for b in entry.bullets) and (op.order or []) != ids:
                reject(i, op, "locked", f"{op.target} has locked bullets and can't be reordered.")
                continue
            valid.append((i, op))
        elif op.op in ("reorder_entries", "drop_entry"):
            sid = op.target if op.op == "reorder_entries" else op.target.split(".")[0]
            sec = doc.section(sid)
            if sec is None:
                reject(i, op, "unknown_target", f"There is no section {sid}.")
                continue
            if sec.kind not in ("projects", "activities") or not sec.entries_reorderable or sec.locked:
                reject(i, op, "structure", f"Entries in '{sec.title}' keep their order; only projects and activities can be reordered or dropped.")
                continue
            if op.op == "reorder_entries":
                ids = [e.id for e in sec.entries]
                if sorted(op.order or []) != sorted(ids):
                    reject(i, op, "structure", f"A reorder of {sid} must list each entry exactly once: {', '.join(ids)}.")
                    continue
            else:
                if doc.entry(op.target) is None:
                    reject(i, op, "unknown_target", f"There is no entry {op.target}.")
                    continue
                n = dropped_entries.get(sid, 0) + 1
                if n >= len(sec.entries):
                    reject(i, op, "structure", f"Dropping {op.target} would leave '{sec.title}' empty.")
                    continue
                lost = _coverage_loss(ctx, [o for _, o in valid], op)
                if lost:
                    reject(i, op, "coverage", f"Dropping {op.target} would remove the only mention of {_and(lost)}, which this job requires. Keep the entry and shorten it instead.")
                    continue
                dropped_entries[sid] = n
            valid.append((i, op))
        else:
            reject(i, op, "structure", f"Unknown operation {op.op}.")

    valid, stuffing = _check_stuffing(valid, ctx)
    violations.extend(stuffing)
    valid, lost = _check_coverage(valid, ctx)
    violations.extend(lost)
    violations.sort(key=lambda v: v.op_index)
    return ValidationResult([op for _, op in valid], violations)


def _check_text(
    op: Op,
    bl: Block,
    doc: ParsedResume,
    ctx: ValidationContext,
    ev_by_id: dict[str, EvidenceItem],
    resume_text: str,
    all_evidence_text: str,
) -> tuple[str, str] | None:
    text = (op.text or "").strip()
    if not text:
        return "empty", f"The new text for {op.target} is empty; use drop to remove a bullet."
    if re.search(r"\\[A-Za-z]+|\\\\", text):
        return "latex", "Write plain text with **bold** only; TailorTeX writes the LaTeX itself."
    plain = text.replace("**", "")
    sec = doc.section(bl.section_id)
    section_kind = sec.kind if sec else "other"

    if op.source == "user":
        return None

    # Length
    budget = doc.bullet_budget
    if bl.kind == "bullet" and len(plain) > budget:
        return "too_long", f"The new text for {op.target} is {len(plain)} characters; keep it under {budget} so it fits on the page."
    if bl.kind == "summary" and len(plain) > budget * 3:
        return "too_long", f"The summary is {len(plain)} characters; keep it under {budget * 3}."

    cited: list[EvidenceItem] = []
    for eid in op.evidence:
        item = ev_by_id.get(eid)
        if item is None:
            return "unknown_evidence", f"Evidence {eid} doesn't exist."
        if not _evidence_allowed_in(item, section_kind, bl.kind):
            where = "the summary or skills" if item.source == "skill" else "projects, activities, the summary or skills"
            return "evidence_scope", f"{eid} ({item.source}) can only support {where}, not a bullet in '{sec.title if sec else op.target}'."
        if item.scope and bl.kind == "bullet" and bl.entry_id != item.scope:
            return "evidence_scope", (
                f"{eid} was found in {item.scope}, and a skill shown in one job or project can't be moved into another's bullets. "
                f"Use it in {item.scope}, in the summary, or in the skills lines."
            )
        cited.append(item)
    cited_text = "\n".join(e.full_text() for e in cited)

    if bl.kind == "skills":
        pool = resume_text + "\n" + all_evidence_text
        items = [x.strip() for x in re.split(r",|;|\u2022|\u00b7|\|", plain) if x.strip()]
        bad = [x for x in items if not contains_term(pool, x) and x.lower() not in pool.lower()]
        if bad:
            return "invented_term", (
                f"{', '.join(repr(b) for b in bad)} {_be(bad)} on the resume or in the evidence bank. "
                "Skills lines can only list skills the candidate is shown to have."
            )
        if len(plain) > max(len(bl.text) * 2, len(bl.text) + 80):
            return "too_long", f"The skills line {op.target} got too long; keep only the most relevant skills."
        return None

    if bl.kind == "summary":
        term_pool = resume_text + "\n" + all_evidence_text
        number_pool = term_pool
    else:
        own = _entry_corpus(doc, bl.entry_id)
        term_pool = "\n".join([own, cited_text])
        heading = doc.entry(bl.entry_id).heading if bl.entry_id and doc.entry(bl.entry_id) else ""
        number_pool = "\n".join([bl.text, heading, cited_text])

    invented = [w for w in specific_terms(plain) if not contains_term(term_pool, w) and not _in_text(term_pool, w)]
    if invented:
        where = "the resume or the evidence bank" if bl.kind == "summary" else "this entry or the evidence it cites"
        hint = "" if bl.kind == "summary" else " A skill used elsewhere can't be moved into this job; cite evidence if the candidate used it here."
        return "invented_term", f"{', '.join(repr(w) for w in invented[:5])} {_be(invented)} supported by {where}.{hint}"

    allowed_numbers = metrics(number_pool)
    bad_numbers = [s for s, v, c in metrics(plain) if not metric_allowed(v, c, allowed_numbers)]
    if bad_numbers:
        return "invented_number", (
            f"{', '.join(repr(n) for n in bad_numbers[:5])} {'doesn' if len(bad_numbers) == 1 else 'don'}'t come from "
            + ("the resume or evidence." if bl.kind == "summary" else "this bullet, its heading or cited evidence. Numbers can't move between bullets.")
        )
    return None


def check_standalone_bullet(text: str, source: str, budget: int) -> tuple[str, str] | None:
    """Check a bullet for a project that isn't on the resume, so it has no entry to borrow facts from.

    The only source of truth is `source`: what the person wrote about it, plus the name, technologies
    and dates they gave. A tool or number that isn't in there is refused, the same way an invented one
    is in an ordinary bullet.
    """
    body = (text or "").strip()
    if not body:
        return "empty", "The bullet is empty."
    if re.search(r"\\[A-Za-z]+|\\\\", body):
        return "latex", "Write plain text with **bold** only; TailorTeX writes the LaTeX itself."
    plain = body.replace("**", "")
    if len(plain) > budget:
        return "too_long", f"The bullet is {len(plain)} characters; keep it under {budget} so it fits on one or two lines."
    invented = [w for w in specific_terms(plain) if not contains_term(source, w) and not _in_text(source, w)]
    if invented:
        return "invented_term", f"{', '.join(repr(w) for w in invented[:5])} {_be(invented)} in what you told us about this project."
    allowed = metrics(source)
    bad = [s_ for s_, val, cls in metrics(plain) if not metric_allowed(val, cls, allowed)]
    if bad:
        return "invented_number", f"{', '.join(repr(n) for n in bad[:5])} {'doesn' if len(bad) == 1 else 'don'}'t come from what you told us about this project."
    return None


def _be(items: list) -> str:
    return "isn't" if len(items) == 1 else "aren't"


def _in_text(pool: str, word: str) -> bool:
    """Plain word-boundary match, for proper nouns the tech matcher doesn't know."""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", pool, re.IGNORECASE) is not None


def _check_coverage(valid: list[tuple[int, Op]], ctx: ValidationContext) -> tuple[list[tuple[int, Op]], list[Violation]]:
    """Refuse the plan's net loss of a must-have keyword, whoever caused it.

    The per-op guard on `drop` catches the obvious case, but it judges each operation on its own: a
    drop can look safe because another bullet still carries the term, and then a rewrite later in the
    same plan removes that one too. Tailoring is meant to raise the match, so the finished plan is
    checked as a whole and the last operation that cost a term is rejected, the way stuffing is.
    """
    if not ctx.analysis or not ctx.protect_coverage:
        return valid, []
    doc = ctx.doc
    musts = [t.term for t, must in ctx.analysis.terms() if must]
    if not musts:
        return valid, []
    before_context, _ = zones_after(doc, [])
    violations: list[Violation] = []
    keep = list(valid)
    for term in musts:
        if not count_term(before_context, term):
            continue  # it wasn't shown in a bullet to begin with, so nothing to protect
        while True:
            after_context, _ = zones_after(doc, [op for _, op in keep])
            if count_term(after_context, term):
                break
            culprit = None
            for i, op in reversed(keep):
                if op.source == "user":
                    continue  # the person wrote this themselves; their wording wins over the score
                was = _op_text_before(doc, op)
                removed = op.op in ("drop", "drop_entry") or (op.op == "rewrite" and count_term(op.text or "", term) < count_term(was, term))
                if removed and count_term(was, term):
                    culprit = (i, op)
                    break
            if culprit is None:
                break
            keep.remove(culprit)
            ci, cop = culprit
            verb = "Dropping" if cop.op in ("drop", "drop_entry") else "This rewrite of"
            violations.append(Violation(ci, cop, "coverage", f"{verb} {cop.target} would leave '{term}' out of every bullet, and this job requires it. Keep it, or work it into another bullet."))
    return keep, violations


def _op_text_before(doc: ParsedResume, op: Op) -> str:
    """The resume text an operation would remove or replace."""
    if op.op == "drop_entry":
        entry = doc.entry(op.target)
        return "\n".join(b.text for b in entry.bullets) if entry else ""
    block = doc.block(op.target)
    return block.text if block else ""


def _check_stuffing(valid: list[tuple[int, Op]], ctx: ValidationContext) -> tuple[list[tuple[int, Op]], list[Violation]]:
    if not ctx.analysis:
        return valid, []
    doc = ctx.doc
    base: dict[str, str] = {b.id: b.text for b in doc.all_blocks() if b.kind in ("bullet", "summary")}
    texts = dict(base)
    added: dict[int, str] = {}
    for i, op in valid:
        if op.op == "rewrite" and op.target in texts:
            texts[op.target] = op.text or ""
        elif op.op == "drop":
            texts.pop(op.target, None)
        elif op.op == "add":
            added[i] = op.text or ""
    violations: list[Violation] = []
    keep = list(valid)
    for t, _must in ctx.analysis.terms():
        before = sum(count_term(x, t.term) for x in base.values())
        limit = max(ctx.max_keyword_uses, before)
        while True:
            current = {op.target: texts.get(op.target, "") for _, op in keep if op.op == "rewrite"}
            total = sum(count_term(x, t.term) for bid, x in texts.items()) + sum(count_term(x, t.term) for i, x in added.items() if any(k == i for k, _ in keep))
            if total <= limit:
                break
            # Reject the last change that added this keyword.
            culprit = None
            for i, op in reversed(keep):
                if op.op == "rewrite" and count_term(current.get(op.target, ""), t.term) > count_term(base.get(op.target, ""), t.term):
                    culprit = (i, op)
                    break
                if op.op == "add" and count_term(op.text or "", t.term) > 0:
                    culprit = (i, op)
                    break
            if culprit is None:
                break
            keep.remove(culprit)
            ci, cop = culprit
            if cop.op == "rewrite":
                texts[cop.target] = base.get(cop.target, "")
            violations.append(Violation(ci, cop, "stuffing", f"'{t.term}' would appear {total} times; use each keyword at most {ctx.max_keyword_uses} times across bullets."))
    return keep, violations


def is_tech(word: str) -> bool:
    return is_known_tech(word)

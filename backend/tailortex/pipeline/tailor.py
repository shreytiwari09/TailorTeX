"""The full tailoring run.

1. Parse the resume and compile the original for "before" numbers.
2. Analyze the job description (LLM) and sort its terms into gap chips.
3. For each strategy the bandit picks, in parallel:
   plan edits (LLM) -> validate -> send rejections back (up to 2 retries)
   -> apply -> compile -> drop the least relevant bullets until it fits the page -> score.
4. Keep the candidate with the highest reward.

Progress events stream out through `emit` as each stage happens.
"""

from __future__ import annotations

import asyncio
import base64
import re
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..ats.coverage import Gap, coverage_loss, coverage_scores, gap_analysis, term_coverage, title_alignment
from ..ats.gain import ats_score, gap_gains, per_change_gains, quality_gain
from ..ats.health import apply_lint_fix, find_stray_breaks, health_score, lint_source, parse_health
from ..ats.quality import quality_report
from ..ats.recommend import recommendations
from ..ats.terms import contains_term, count_term, same_term
from ..compile.compile import CompileResult, UnsafeLatexError, compile_async, detect_engine, tex_available
from ..latex.apply import ApplyError, apply_ops
from ..latex.parse import ParsedResume, parse_resume
from ..latex.text import plain_to_latex
from ..latex.snippet import MAX_BULLETS, insert_project, project_block, project_style
from ..learn.arms import ARMS
from ..learn.bandit import Bandit, context_key
from ..learn.style import StyleMemory
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import ANALYZE_SYSTEM, analyze_user, chat_system, chat_user, draft_system, draft_user, plan_system, plan_user, retry_user
from ..llm.schemas import ChatTurn, Draft, Plan
from ..ops import Op
from ..reward.reward import RewardInput, reward
from ..evidence.answers import answer_to_evidence, next_answer_number
from ..evidence.extract import known_skills
from ..evidence.support import derive_evidence, find_support
from ..types import Answer, EvidenceItem, JobAnalysis, ProjectInfo
from ..validate.validate import ValidationContext, Violation, check_standalone_bullet, validate_ops

Emit = Callable[[dict], Awaitable[None]]
# Picks the background items to use for a job: (items to use, a message for the progress log).
Ranker = Callable[[JobAnalysis, list[EvidenceItem]], Awaitable[tuple[list[EvidenceItem], str | None]]]
MAX_RETRIES = 2
MAX_FIT_DROPS = 8
MAX_DRAFT_RETRIES = 1  # one repair pass: each round costs a model call, and free tiers allow about twenty a day


class TailorError(Exception):
    pass


@dataclass
class TailorInput:
    tex: str
    jd: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    candidates: int = 1
    compile_pdf: bool = True
    page_limit: int | None = None
    user: str | None = None


@dataclass
class Metrics:
    must_have: float
    nice_to_have: float
    title: float
    health: float | None
    checks: list[dict]
    pages: int | None
    page_fill: float | None
    quality: float = 1.0  # general resume quality, independent of this job
    quality_checks: list[dict] = field(default_factory=list)
    quality_findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Candidate:
    arm: str
    ops: list[Op]
    violations: list[tuple[int, Violation]]
    tex: str
    compiled: CompileResult | None
    metrics: Metrics
    coverage: list
    reward: float
    reward_parts: dict
    attempts: int
    fit_note: str | None = None
    warnings: list[str] = field(default_factory=list)


async def _noop(_event: dict) -> None:
    return None


def _event(stage: str, status: str, message: str, data: dict | None = None) -> dict:
    return {"type": "progress", "stage": stage, "status": status, "message": message, "data": data or {}}


def clean_analysis(a: JobAnalysis) -> JobAnalysis:
    """Drop empty, overlong and duplicate terms; a must-have wins over a nice-to-have."""
    seen: list[str] = []

    def keep(terms, limit):
        out = []
        for t in terms:
            term = re.sub(r"\s+", " ", t.term or "").strip(" .,;:")
            if not term or len(term) > 60 or any(same_term(term, s) for s in seen):
                continue
            seen.append(term)
            t.term = term
            out.append(t)
        return out[:limit]

    a.must_have = keep(a.must_have, 15)
    a.nice_to_have = keep(a.nice_to_have, 12)
    return a


def measure(doc: ParsedResume, analysis: JobAnalysis, compiled: CompileResult | None) -> tuple[Metrics, list]:
    text = compiled.text if compiled and compiled.ok else None
    cov = term_coverage(doc, analysis, text)
    must, nice = coverage_scores(cov)
    checks = parse_health(text, doc) if text is not None else []
    quality, qchecks, qfindings = quality_report(doc)
    return (
        Metrics(
            must_have=round(must, 4),
            nice_to_have=round(nice, 4),
            title=round(title_alignment(doc, analysis.title), 4),
            health=round(health_score(checks), 4) if checks else None,
            checks=[c.to_dict() for c in checks],
            pages=compiled.pages if compiled and compiled.ok else None,
            page_fill=compiled.page_fill if compiled and compiled.ok else None,
            quality=quality,
            quality_checks=[c.to_dict() for c in qchecks],
            quality_findings=[f.to_dict() for f in qfindings],
        ),
        cov,
    )


def _relevance(text: str, analysis: JobAnalysis) -> float:
    return sum(count_term(text, t.term) * t.weight * (2 if must else 1) for t, must in analysis.terms())


def _fit_candidates(doc: ParsedResume, ops: list[Op], analysis: JobAnalysis) -> list[Op]:
    """Bullets that can be dropped to save space, least relevant first.

    A bullet is only offered if the resume still shows every must-have keyword it carries afterwards:
    dropping the one bullet that mentions Kubernetes to save a line would lower the very score the
    page fit is protecting.
    """
    dropped = {o.target for o in ops if o.op == "drop"}
    dropped_entries = {o.target for o in ops if o.op == "drop_entry"}
    rewrites = {o.target: o.text or "" for o in ops if o.op == "rewrite"}
    ranked: list[tuple[tuple, str]] = []
    for s in doc.sections:
        if s.locked or s.kind not in ("experience", "projects", "activities"):
            continue
        for e in s.entries:
            if e.id in dropped_entries:
                continue
            alive = [b for b in e.bullets if b.id not in dropped]
            added = sum(1 for o in ops if o.op == "add" and o.target == e.id)
            if len(alive) + added <= 1:
                continue
            for b in alive:
                if b.locked:
                    continue
                text = rewrites.get(b.id, b.text)
                ranked.append(((_relevance(text, analysis), -(len(alive) + added), -len(text)), b.id))
    ranked.sort(key=lambda x: x[0])

    out: list[Op] = []
    for _, bullet_id in ranked:
        op = Op(op="drop", target=bullet_id, reason="Removed to keep the page limit: the least relevant bullet for this job.", source="fit")
        if coverage_loss(doc, analysis, ops, op):
            continue
        out.append(op)
    return out


def _fit_candidate(doc: ParsedResume, ops: list[Op], analysis: JobAnalysis) -> Op | None:
    """The least relevant bullet that can be dropped without losing a must-have keyword."""
    return next(iter(_fit_candidates(doc, ops, analysis)), None)


async def _repair_original(tex: str) -> tuple[str, CompileResult, str] | None:
    """Try the safe, known fixes for a resume that won't compile. Returns (fixed source, its compile, a note)
    only if the fixed file really does compile, so a repair can never make things worse."""
    stray = find_stray_breaks(tex)
    if stray:
        fixed = apply_lint_fix(tex, "stray_linebreak")
        if fixed != tex:
            result = await compile_async(fixed)
            if result.ok:
                where = f"line {stray[0][0]}"
                return fixed, result, (
                    f"Your resume wouldn't compile because {where} starts with a line break that has nothing before it to end. "
                    "We removed it in this version so you get a PDF. Remove it from your Overleaf file too."
                )
    return None


_SKILL_SPLIT = re.compile(r"\s*(?:,|;|\u2022|\u00b7|\|)\s*")


def skill_items(text: str) -> list[str]:
    return [x.strip() for x in _SKILL_SPLIT.split(text.replace("**", "")) if x.strip()]


def skill_separator(original: str) -> str:
    """How this skills line separates its items: the resume's own style, not the model's."""
    return " \u2022 " if "\u2022" in original else " \u00b7 " if "\u00b7" in original else ", "


def normalize_ops(doc: ParsedResume, ops: list[Op]) -> list[Op]:
    """Small, safe fixes to model output: a skills line's text shouldn't repeat its label, and it keeps the
    separator the line was written with (a bulleted line stays bulleted)."""
    for op in ops:
        if op.op == "rewrite" and op.text:
            b = doc.block(op.target)
            if b and b.kind == "skills":
                if b.label:
                    op.text = re.sub(r"^\s*\**\s*" + re.escape(b.label) + r"\s*\**\s*:\s*\**\s*", "", op.text, flags=re.IGNORECASE)
                op.text = skill_separator(b.text).join(skill_items(op.text))
    return ops


def _apply_safely(doc: ParsedResume, ops: list[Op]) -> tuple[str, list[Op], list[str]]:
    try:
        return apply_ops(doc, ops), ops, []
    except ApplyError as e:
        # Keep plain rewrites, which can't conflict, and report the rest.
        safe = [o for o in ops if o.op == "rewrite"]
        return apply_ops(doc, safe), safe, [f"Some structural changes couldn't be applied ({e}); kept the rewrites."]


async def _run_candidate(
    arm: str,
    doc: ParsedResume,
    inp: TailorInput,
    analysis: JobAnalysis,
    gaps: list[Gap],
    llm: LLMClient,
    compile_pdf: bool,
    page_limit: int,
    style: tuple[list[str], list[str]],
    emit: Emit,
) -> Candidate:
    vctx = ValidationContext(doc=doc, evidence=inp.evidence, analysis=analysis)
    system = plan_system(doc.bullet_budget, ARMS[arm], *style)
    base = plan_user(doc, inp.evidence, analysis, gaps, inp.jd)
    message = base
    all_violations: list[tuple[int, Violation]] = []
    valid: list[Op] = []
    attempts = 0
    for attempt in range(1, MAX_RETRIES + 2):
        attempts = attempt
        await emit(_event("plan", "start", f"[{arm}] Planning edits" + (f" (retry {attempt - 1})" if attempt > 1 else "")))
        plan = await llm.complete(system, message, Plan)
        ops = normalize_ops(doc, [p.to_op() for p in plan.ops])
        result = validate_ops(ops, vctx)
        valid = result.valid
        for v in result.violations:
            all_violations.append((attempt, v))
        await emit(_event(
            "validate", "done" if not result.violations else "warn",
            f"[{arm}] {len(valid)} edits passed the guardrails" + (f", {len(result.violations)} blocked" if result.violations else ""),
            {"arm": arm, "attempt": attempt, "blocked": [{"op": v.op.describe(), "rule": v.rule, "message": v.message, "text": v.op.text} for v in result.violations]},
        ))
        if not result.violations:
            break
        if attempt <= MAX_RETRIES:
            message = retry_user(base, [o.model_dump(exclude={"source"}) for o in ops], [f"{v.op.describe()}: {v.message}" for v in result.violations])

    tex, applied, warnings = _apply_safely(doc, valid)
    compiled: CompileResult | None = None
    fit_note = None
    if compile_pdf:
        await emit(_event("compile", "start", f"[{arm}] Compiling"))
        compiled = await compile_async(tex)
        if not compiled.ok:
            # Shouldn't happen (all text is escaped), but never return a broken file.
            warnings.append("The edited file didn't compile, so structural edits were undone.")
            tex, applied, _ = _apply_safely(doc, [o for o in applied if o.op == "rewrite"])
            compiled = await compile_async(tex)
            if not compiled.ok:
                tex, applied = doc.source, []
                compiled = await compile_async(tex)
        drops = 0
        while compiled.ok and compiled.pages > page_limit and drops < MAX_FIT_DROPS:
            op = _fit_candidate(doc, applied, analysis)
            if op is None:
                break
            applied = applied + [op]
            drops += 1
            tex, applied, _ = _apply_safely(doc, applied)
            await emit(_event("fit", "info", f"[{arm}] {compiled.pages} pages, limit {page_limit}: dropping the least relevant bullet"))
            compiled = await compile_async(tex)
        if drops:
            fit_note = f"Dropped {drops} low-relevance bullet{'s' if drops > 1 else ''} to fit {page_limit} page{'s' if page_limit > 1 else ''}."
        if compiled.ok and compiled.pages > page_limit:
            warnings.append(f"The result is {compiled.pages} pages; the limit is {page_limit}.")
        await emit(_event("compile", "done" if compiled.ok else "warn", f"[{arm}] Compiled: {compiled.pages} page{'s' if compiled.pages != 1 else ''}" if compiled.ok else f"[{arm}] Compile failed"))

    new_doc = parse_resume(tex)
    metrics, cov = measure(new_doc, analysis, compiled)
    stuffing = sum(1 for _, v in all_violations if v.rule == "stuffing")
    r = reward(RewardInput(
        valid=True,
        compiled=compiled.ok if compiled else True,
        pages=compiled.pages if compiled and compiled.ok else 1,
        page_limit=page_limit if compiled else 1,
        must_have=metrics.must_have,
        nice_to_have=metrics.nice_to_have,
        title=metrics.title,
        parse_health=metrics.health if metrics.health is not None else 1.0,
        page_fill=metrics.page_fill,
        bullet_quality=metrics.quality,
        stuffing=stuffing,
    ))
    await emit(_event("score", "done", f"[{arm}] Score {r.total:.2f}: must-have coverage {metrics.must_have:.0%}", {"arm": arm, "reward": r.total}))
    return Candidate(arm, applied, all_violations, tex, compiled, metrics, cov, r.total, r.parts, attempts, fit_note, warnings)


def suggested_filename(doc: ParsedResume, analysis: JobAnalysis) -> str:
    """First_Last_Company_Role, the naming recruiters expect."""

    def word(text: str) -> str:
        return "".join(re.sub(r"[^A-Za-z0-9]+", "", w[:1].upper() + w[1:]) for w in text.split())

    parts = [re.sub(r"[^A-Za-z0-9]+", "", w) for w in doc.name().split()[:3]]
    parts += [word(analysis.company or ""), word(re.sub(r"\(.*?\)", "", analysis.title or ""))]
    name = "_".join(p for p in parts if p)
    return (name or "Resume")[:80]


def describe_changes(doc: ParsedResume, ops: list[Op], analysis: JobAnalysis | None = None) -> list[dict]:
    out = []
    worth = per_change_gains(doc, ops, analysis) if analysis is not None else [{"terms": [], "gain": 0.0}] * len(ops)
    for i, op in enumerate(ops):
        sec = doc.section_of(op.target)
        item = {
            "id": i, "op": op.op, "target": op.target, "reason": op.reason, "evidence": op.evidence,
            "terms": worth[i]["terms"], "gain": worth[i]["gain"],
            "source": op.source, "section": sec.title if sec else "", "heading": "", "before": "", "after": "",
            "before_list": None, "after_list": None,
        }
        if op.op in ("rewrite", "drop"):
            b = doc.block(op.target)
            if b:
                item["before"] = b.text
                e = doc.entry(b.entry_id) if b.entry_id else None
                item["heading"] = e.heading if e else (b.label or "")
            item["after"] = op.text or "" if op.op == "rewrite" else ""
        elif op.op == "add":
            e = doc.entry(op.target)
            item["heading"] = e.heading if e else ""
            item["after"] = op.text or ""
        elif op.op == "reorder":
            e = doc.entry(op.target)
            if e:
                item["heading"] = e.heading
                texts = {b.id: b.text for b in e.bullets}
                item["before_list"] = [b.text for b in e.bullets]
                item["after_list"] = [texts.get(x, x) for x in op.order or []]
        elif op.op in ("reorder_entries", "drop_entry"):
            s = doc.section(op.target.split(".")[0])
            if s:
                heads = {e.id: e.heading for e in s.entries}
                if op.op == "reorder_entries":
                    item["before_list"] = [e.heading for e in s.entries]
                    item["after_list"] = [heads.get(x, x) for x in op.order or []]
                else:
                    item["before"] = heads.get(op.target, "")
                    item["heading"] = heads.get(op.target, "")
        out.append(item)
    return out


def keyword_table(before: list, after: list, gaps: list[Gap]) -> list[dict]:
    b = {c.term: c for c in before}
    g = {x.term: x for x in gaps}
    rows = []
    for c in after:
        prev = b.get(c.term)
        rows.append({
            "term": c.term, "weight": c.weight, "must": c.must,
            "before": prev.status if prev else "missing", "after": c.status,
            "in_pdf": c.in_pdf, "gap": g[c.term].status if c.term in g else None,
            "evidence_ids": g[c.term].evidence_ids if c.term in g else [],
        })
    return rows


def background_suggestions(doc: ParsedResume, tailored: ParsedResume, analysis: JobAnalysis, evidence: list[EvidenceItem], ops: list[Op]) -> list[dict]:
    """Items from the user's background (GitHub, LinkedIn, portfolio, facts, skills) that cover job keywords
    the original resume didn't have: which were used in this version, and which are still worth adding."""
    before_text = doc.plain_text()
    after_text = tailored.plain_text()
    cited = {e for op in ops for e in op.evidence}
    out = []
    for ev in evidence:
        text = ev.full_text()
        covers = [(t.term, must) for t, must in analysis.terms() if contains_term(text, t.term) or any(same_term(sk, t.term) for sk in ev.skills)]
        new = [(term, must) for term, must in covers if not contains_term(before_text, term)]
        if not new:
            continue
        out.append({
            "id": ev.id, "title": ev.title, "source": ev.source, "url": ev.url,
            "added": [term for term, _ in new if contains_term(after_text, term)],
            "still_missing": [term for term, _ in new if not contains_term(after_text, term)],
            "must": [term for term, must in new if must],
            "cited": ev.id in cited,
        })
    out.sort(key=lambda x: (-len(x["still_missing"]) - len(x["added"]), -len(x["must"])))
    return out


def build_result(run_id: str, doc: ParsedResume, analysis: JobAnalysis, gaps: list[Gap], before: Metrics, before_cov: list,
                 best: Candidate, cands: list[Candidate], ctx: str, llm: LLMClient, page_limit: int, warnings: list[str],
                 evidence: list[EvidenceItem] | None = None) -> dict:
    compiled = best.compiled
    blocked = [
        {"attempt": att, "arm": best.arm, "op": v.op.describe(), "rule": v.rule, "message": v.message, "text": v.op.text, "retried": att < best.attempts}
        for att, v in best.violations
    ]
    left_out = [
        {"term": gp.term, "must": gp.must, "weight": gp.weight}
        for gp in gaps if gp.status == "missing"
    ]
    result = {
        "type": "result",
        "run_id": run_id,
        "arm": best.arm,
        "context": ctx,
        "candidates": [{"arm": c.arm, "reward": c.reward, "must_have": c.metrics.must_have, "applied": len(c.ops), "blocked": len(c.violations)} for c in cands],
        "reward": best.reward,
        "reward_parts": best.reward_parts,
        "analysis": analysis.model_dump(),
        "gaps": [gp.to_dict() for gp in gaps],
        "before": before.to_dict(),
        "after": best.metrics.to_dict(),
        "keywords": keyword_table(before_cov, best.coverage, gaps),
        "changes": describe_changes(doc, best.ops, analysis),
        "ops": [o.model_dump() for o in best.ops],
        "blocked": blocked,
        "left_out": left_out,
        "suggestions": background_suggestions(doc, parse_resume(best.tex), analysis, evidence or [], best.ops),
        "fit_note": best.fit_note,
        "tex": best.tex,
        "source_tex": doc.source,
        "pdf": base64.b64encode(compiled.pdf).decode() if compiled and compiled.ok and compiled.pdf else None,
        "page_limit": page_limit,
        "filename": suggested_filename(doc, analysis),
        "engine": detect_engine(doc.source),
        "usage": {"provider": llm.provider, "model": llm.model, "input_tokens": llm.usage.input_tokens, "output_tokens": llm.usage.output_tokens, "calls": llm.usage.calls},
        "warnings": warnings + best.warnings,
    }
    before_d, after_d = before.to_dict(), best.metrics.to_dict()
    result["ats"] = {"before": ats_score(before_d), "after": ats_score(after_d)}
    lost = result["ats"]["before"] - result["ats"]["after"]
    if best.ops and lost > 0.001:
        # The keyword guard can't see everything: a rewrite can read worse without losing a keyword. Say so,
        # so the person knows to look, instead of showing a score that quietly went down.
        weaker = [c["label"] for c in (best.metrics.quality_checks or []) if not c.get("ok")]
        why = f" It mostly comes from how the reworded bullets read ({', '.join(weaker[:2]).lower()})." if weaker and best.metrics.quality < before.quality else ""
        result["warnings"].append(f"This version scores {lost * 100:.1f}% lower than your original.{why} Untick the changes that don't help, or keep your original wording.")
    result["gains"] = {
        "gaps": gap_gains(analysis, result["gaps"], result["keywords"]),
        "quality": quality_gain(before.quality, best.metrics.quality),
    }
    result["recommendations"] = recommendations(result, {e.id: e.title or e.text[:40] for e in evidence or []})
    return result


async def tailor(
    inp: TailorInput, llm: LLMClient, emit: Emit = _noop, bandit: Bandit | None = None,
    style_memory: StyleMemory | None = None, ranker: Ranker | None = None,
) -> dict:
    run_id = uuid.uuid4().hex[:12]
    warnings: list[str] = []
    doc = parse_resume(inp.tex)
    editable = doc.editable_blocks()
    total_bullets = sum(len(e.bullets) for s in doc.sections for e in s.entries)
    if not doc.sections:
        raise TailorError("Couldn't find any sections. TailorTeX needs \\section{...} (or \\cvsection) headings.")
    if not editable:
        raise TailorError("No editable bullets were found. TailorTeX edits \\item bullets and \\resumeItem-style macros.")
    await emit(_event("parse", "done", f"Found {len(doc.sections)} sections and {total_bullets} bullets ({len(editable)} editable blocks, {doc.profile} template)"))

    compile_pdf = inp.compile_pdf and tex_available()
    if inp.compile_pdf and not compile_pdf:
        warnings.append("LaTeX isn't installed on the server, so no PDF was compiled. The .tex is still tailored and checked.")
    before_compiled: CompileResult | None = None
    if compile_pdf:
        await emit(_event("compile_original", "start", "Compiling your original resume"))
        try:
            before_compiled = await compile_async(inp.tex)
        except UnsafeLatexError as e:
            raise TailorError(str(e)) from None
        repaired = await _repair_original(inp.tex) if not before_compiled.ok else None
        if repaired is not None:
            inp.tex, before_compiled, note = repaired
            doc = parse_resume(inp.tex)  # ids are unchanged: only a line break was removed
            warnings.append(note)
            await emit(_event("compile_original", "warn", note))
        if not before_compiled.ok:
            err = before_compiled.errors[0] if before_compiled.errors else None
            msg = f"Your original resume doesn't compile ({err.message}{f', line {err.line}' if err and err.line else ''}), so PDF checks are off for this run." if err else "Your original resume doesn't compile."
            warnings.append(msg)
            await emit(_event("compile_original", "warn", msg))
            compile_pdf = False
            before_compiled = None
        else:
            await emit(_event("compile_original", "done", f"Original: {before_compiled.pages} page{'s' if before_compiled.pages != 1 else ''}, compiled with {before_compiled.engine}"))
    page_limit = inp.page_limit or (before_compiled.pages if before_compiled else 1)

    for issue in lint_source(doc, detect_engine(inp.tex)):
        if issue.severity == "warn":
            warnings.append(issue.message)

    await emit(_event("analyze", "start", "Reading the job description"))
    analysis = clean_analysis(await llm.complete(ANALYZE_SYSTEM, analyze_user(inp.jd), JobAnalysis))
    if not analysis.must_have and not analysis.nice_to_have:
        raise TailorError("Couldn't find any skills or requirements in the job description. Paste the full posting.")
    await emit(_event(
        "analyze", "done",
        f"{analysis.title or 'Role'}" + (f" at {analysis.company}" if analysis.company else "") + f": {len(analysis.must_have)} must-haves, {len(analysis.nice_to_have)} nice-to-haves",
        {"analysis": analysis.model_dump()},
    ))

    if ranker is not None and inp.evidence:
        await emit(_event("background", "start", "Finding what in your background fits this job"))
        inp.evidence, message = await ranker(analysis, inp.evidence)
        if message:
            await emit(_event("background", "done", message))

    gaps = gap_analysis(doc, analysis, inp.evidence)
    # A skill can be shown in other words than the job uses. Ask the person's own material, by meaning,
    # before calling it missing.
    supports = await find_support(doc, analysis, gaps, inp.evidence, llm)
    inferred_evidence = derive_evidence(supports)
    if supports:
        inp.evidence = [*inp.evidence, *inferred_evidence]
        gaps = gap_analysis(doc, analysis, inp.evidence)
        await emit(_event("gaps", "info", f"Found {len(supports)} skill{'s' if len(supports) != 1 else ''} your own material already shows: {', '.join(s.term for s in supports[:4])}"))
    counts = {k: sum(1 for g in gaps if g.status == k) for k in ("present", "evidence", "missing")}
    await emit(_event("gaps", "done", f"{counts['present']} already on your resume, {counts['evidence']} backed by your evidence, {counts['missing']} with no evidence (won't be added)", {"gaps": [g.to_dict() for g in gaps]}))
    before, before_cov = measure(doc, analysis, before_compiled)

    bandit = bandit or Bandit()
    style_memory = style_memory or StyleMemory()
    ctx = context_key(analysis.title, analysis.role_family, analysis.seniority)
    arms = bandit.choose(ctx, inp.candidates, inp.user)
    style = style_memory.get(inp.user)
    await emit(_event("strategy", "info", f"Trying {len(arms)} strateg{'ies' if len(arms) > 1 else 'y'}: {', '.join(arms)}", {"arms": arms, "context": ctx}))

    results = await asyncio.gather(
        *(_run_candidate(arm, doc, inp, analysis, gaps, llm, compile_pdf, page_limit, style, emit) for arm in arms),
        return_exceptions=True,
    )
    cands = [c for c in results if isinstance(c, Candidate)]
    if not cands:
        err = next((r for r in results if isinstance(r, Exception)), None)
        if isinstance(err, LLMError):
            raise err
        raise TailorError(f"Tailoring failed: {err}") from err
    for r in results:
        if isinstance(r, LLMError):
            warnings.append(f"One strategy failed: {r}")
    best = max(cands, key=lambda c: (c.reward, -len(c.violations)))
    result = build_result(run_id, doc, analysis, gaps, before, before_cov, best, cands, ctx, llm, page_limit, warnings, inp.evidence)
    # What was found in their own material, for the page to show, and the evidence a rebuild needs to re-validate
    result["inferred"] = [s.to_dict() for s in supports]
    result["inferred_evidence"] = [e.model_dump() for e in inferred_evidence]
    await emit(_event("done", "done", f"Done. Must-have coverage {before.must_have:.0%} → {best.metrics.must_have:.0%}"))
    return result


async def rebuild(tex: str, ops: list[Op], analysis: JobAnalysis, evidence: list[EvidenceItem], compile_pdf: bool = True, page_limit: int | None = None) -> dict:
    """Re-apply a chosen subset of changes (after reverts and edits), compile and re-measure."""
    doc = parse_resume(tex)
    result = validate_ops(ops, ValidationContext(doc=doc, evidence=evidence, analysis=analysis, max_keyword_uses=10**6))
    new_tex, applied, warnings = _apply_safely(doc, result.valid)
    warnings += [f"{v.op.describe()}: {v.message}" for v in result.violations]
    compiled = await compile_async(new_tex) if compile_pdf and tex_available() else None
    if compiled and not compiled.ok:
        # A run saved before the resume was fixed still holds the broken source. Repair it here too, so
        # pressing Apply gives a PDF instead of failing on the same line.
        repaired = await _repair_original(new_tex)
        if repaired is not None:
            new_tex, compiled, note = repaired
            warnings.append(note)
    if compiled and not compiled.ok:
        warnings.append("The edited file didn't compile: " + (compiled.errors[0].message if compiled.errors else "unknown error"))
    new_doc = parse_resume(new_tex)
    metrics, cov = measure(new_doc, analysis, compiled)
    # What the resume shows now, and what is still unbacked: an answer the person has just given must
    # stop being offered as a gap.
    gaps = gap_analysis(new_doc, analysis, evidence)
    keywords = keyword_table(cov, cov, gaps)
    limit = page_limit or 1
    if compiled and compiled.ok and compiled.pages > limit:
        warnings.append(f"The result is {compiled.pages} pages; the limit is {limit}. Revert an added bullet or keep a page-fit drop.")
    return {
        "tex": new_tex,
        "pdf": base64.b64encode(compiled.pdf).decode() if compiled and compiled.ok and compiled.pdf else None,
        "after": metrics.to_dict(),
        "coverage": [c.to_dict() for c in cov],
        "keywords": keywords,
        "gaps": [g.to_dict() for g in gaps],
        "gap_gains": gap_gains(analysis, [g.to_dict() for g in gaps], keywords),
        "applied": [o.model_dump() for o in applied],
        "warnings": warnings,
    }



def _accepted_overlay(doc: ParsedResume, accepted: list[Op]) -> dict[str, str | None]:
    """What each block reads as once the already-accepted changes are in, so a draft sees the current
    wording while its block ids stay those of the original file."""
    overlay: dict[str, str | None] = {}
    for op in accepted:
        if op.op == "rewrite" and op.text is not None:
            overlay[op.target] = op.text
        elif op.op == "drop":
            overlay[op.target] = None
    return overlay


def _said(text: str, phrase: str) -> bool:
    """Whether the person's own words contain this phrase, ignoring case and spacing."""
    flat = lambda x: re.sub(r"\s+", " ", x).strip().lower()  # noqa: E731
    return bool(phrase.strip()) and flat(phrase) in flat(text)


def _project_from_reply(answer: Answer, item: EvidenceItem, pd) -> ProjectInfo | None:
    """The project a reply describes, using only what the reply says.

    A project the person marked is used as given. One the model recognised in a plain reply keeps its name,
    dates and technologies only if they appear in the reply's own words: a model that invents a tidy name
    ("Fraud Detector") for something the person never named gets no project, and they are asked instead.
    """
    if answer.project is not None:
        return answer.project
    if answer.target:
        return None
    name = pd.name.strip()
    if len(name) < 2 or not _said(item.text, name):
        return None
    dates = pd.dates.strip() if _said(item.text, pd.dates) else ""
    tech = [t for t in pd.tech if _said(item.text, t)] or known_skills(item.text)[:8]
    return ProjectInfo(name=name[:120], dates=dates[:40], tech=tech[:12])


async def answer_gaps(
    source_tex: str,
    analysis: JobAnalysis,
    evidence: list[EvidenceItem],
    answers: list[Answer],
    accepted: list[Op],
    llm: LLMClient,
    emit: Emit = _noop,
    current_tex: str | None = None,
    page_limit: int | None = None,
) -> dict:
    """Turn the person's own words into checked bullets. One model call covers every answer.

    An answer about something they did *inside* a job or project they already have becomes an `add`
    operation on that entry. An answer about a *separate* project can't: TailorTeX can't create an
    entry, so it becomes a block of LaTeX in the resume's own style, with a copy of the resume that has
    it added, for the person to paste into Overleaf.

    Nothing is applied to the saved resume here. The drafted operations keep source="model", which is
    load-bearing: source="user" skips every fabrication check, which is right for text a person typed and
    wrong for text a model wrote from their answer. The answer is the evidence, so a tool or number that
    isn't in what they said is rejected like any other invention.
    """
    doc = parse_resume(source_tex)
    first = next_answer_number([e.id for e in evidence])
    stored = [answer_to_evidence(a.term, a.text, first + i, a.project.name if a.project else None) for i, a in enumerate(answers)]
    all_evidence = [*evidence, *stored]
    overlay = _accepted_overlay(doc, accepted)
    accepted_targets = {o.target for o in accepted}
    by_id = {item.id: (a, item) for a, item in zip(answers, stored)}

    system = draft_system(doc.bullet_budget)
    base = draft_user(doc, overlay, all_evidence, list(zip(answers, stored)), analysis)
    vctx = ValidationContext(doc=doc, evidence=all_evidence, analysis=analysis)

    await emit(_event("draft", "start", f"Writing from {len(answers)} answer{'s' if len(answers) != 1 else ''}"))
    message, blocked, followups = base, [], []
    ops: list[Op] = []
    projects: dict[str, list[str]] = {}
    for attempt in range(1, MAX_DRAFT_RETRIES + 2):
        draft = await llm.complete(system, message, Draft)
        # a separate project has no entry to add to, so an operation that cites its answer is dropped
        ops = normalize_ops(doc, [p.to_op() for p in draft.ops if not any(e in by_id and by_id[e][0].project for e in (p.evidence or []))])
        followups = [f.model_dump() for f in draft.followups]
        result = validate_ops(ops, vctx)
        blocked = [{"attempt": attempt, "op": v.op.describe(), "rule": v.rule, "message": v.message, "text": v.op.text, "retried": attempt <= MAX_DRAFT_RETRIES}
                   for v in result.violations]

        # bullets for separate projects have no entry to borrow from: only the person's own words count
        projects, rejected = {}, []
        infos = {}
        for pd in draft.projects:
            pair = by_id.get(pd.answer)
            if pair is None:
                continue
            a, item = pair
            info = _project_from_reply(a, item, pd)
            if info is None:
                continue
            infos[pd.answer] = info
            source = "\n".join([item.text, info.name, ", ".join(info.tech), info.dates])
            good = []
            for b in pd.bullets[:8]:
                problem = check_standalone_bullet(b, source, doc.bullet_budget)
                if problem is None:
                    good.append(b)
                else:
                    rejected.append(f"Project '{info.name}': {problem[1]}")
                    blocked.append({"attempt": attempt, "op": f"project {info.name}", "rule": problem[0], "message": problem[1], "text": b, "retried": attempt <= MAX_DRAFT_RETRIES})
            if good:
                projects[pd.answer] = good

        problems = [f"{v.op.describe()}: {v.message}" for v in result.violations] + rejected
        if not problems or attempt > MAX_DRAFT_RETRIES:
            break
        message = retry_user(base, [o.model_dump() for o in ops], problems)

    valid = result.valid
    # a new bullet may not land on a block the person already changed: the newer suggestion replaces it
    superseded = [o.target for o in valid if o.target in accepted_targets and o.op != "add"]
    changes = describe_changes(doc, valid, analysis)

    # an answer that became a bullet on an entry isn't also a separate project
    cited = {e for o in valid for e in o.evidence}
    projects = {aid: b for aid, b in projects.items() if aid not in cited}
    snippets = [await _project_snippet(doc, analysis, by_id[aid][0], by_id[aid][1], bullets, current_tex or source_tex, page_limit, infos[aid])
                for aid, bullets in projects.items()]
    asked = {f["term"] for f in followups}
    for a, item in by_id.values():
        if item.id in projects or item.id in cited or a.term in asked:
            continue
        if a.project:
            followups.append({"term": a.term, "question": f"Tell me a bit more about {a.project.name}: what did you build, what did you use, and what came of it?"})
        elif not a.target and not valid and not projects:
            followups.append({"term": a.term, "question": f"What was the project called, and roughly when did you do it? Or tell me which job or project on your resume it belongs to."})

    n = len(valid) + len(snippets)
    await emit(_event("draft", "done", f"{n} thing{'s' if n != 1 else ''} ready to review"))
    return {
        "ops": [o.model_dump() for o in valid],
        "changes": changes,
        "projects": snippets,
        "blocked": blocked,
        "followups": followups,
        "superseded": superseded,
        "evidence": [e.model_dump() for e in stored],
    }


async def _project_snippet(doc: ParsedResume, analysis: JobAnalysis, answer: Answer, item: EvidenceItem,
                           bullets: list[str], current_tex: str, page_limit: int | None, info: ProjectInfo) -> dict:
    """The LaTeX for a new project, the resume with it added, and what adding it is worth."""
    current = parse_resume(current_tex)
    block = project_block(current, info.name, info.dates, info.tech, bullets)
    merged, where = insert_project(current, block)
    compiled = await compile_async(merged) if tex_available() else None
    ok = None if compiled is None else compiled.ok

    # worth: measured the same way both sides (no PDF), so the difference is the project alone
    before, cov_before = measure(current, analysis, None)
    after, cov_after = measure(parse_resume(merged), analysis, None)
    was = {c.term: c.status for c in cov_before}
    gained = [c.term for c in cov_after if c.status == "context" and was.get(c.term) != "context"]
    limit = page_limit or (compiled.pages if compiled and compiled.ok else 1)
    return {
        "answer": item.id,
        "term": answer.term,
        "name": info.name,
        "dates": info.dates,
        "tech": info.tech,
        "style": project_style(current),
        "bullets": bullets[:MAX_BULLETS],
        "latex": block,
        "where": where,
        "tex_with_project": merged,
        "compiles": ok,
        "pages": compiled.pages if compiled and compiled.ok else None,
        "page_limit": limit,
        "over_limit": bool(compiled and compiled.ok and compiled.pages > limit),
        "ats_before": ats_score(before.to_dict()),
        "ats_after": ats_score(after.to_dict()),
        "terms": gained,
    }



def _skill_ops(doc: ParsedResume, accepted: list[Op], adds, item: EvidenceItem, offered: list[str] | None = None) -> tuple[list[Op], list[str], list[dict], list[dict]]:
    """Put the skills a person says they have onto a Skills line.

    Built here rather than left to the model, so the line keeps its own separator and nothing else on it
    changes. A skill the person's own words don't contain is refused on its own, so one stray addition doesn't
    cost them the skills they did name. Returns (operations, things to tell the person, skills that couldn't be
    placed, skills refused).
    """
    editable = [b for sec in doc.sections if sec.kind == "skills" for b in sec.blocks if not b.locked]
    rewritten = {o.target: o.text for o in accepted if o.op == "rewrite" and o.text}
    resume_text = doc.plain_text()
    pending: dict[str, list[str]] = {}
    notes: list[str] = []
    manual: list[dict] = []
    refused: list[dict] = []
    for a in adds:
        term = a.term.strip()
        if not term:
            continue
        # a skill the assistant itself offered from the job's list counts once the person says to add it ("add all")
        if not (contains_term(item.text, term) or _said(item.text, term) or any(same_term(term, o) for o in offered or [])):
            refused.append({"op": f"skill {term}", "rule": "invented_term", "message": f"'{term}' isn't in what you told me, so I didn't add it.", "text": term})
            continue
        already = contains_term(resume_text, term) or any(contains_term(t, term) for t in rewritten.values()) or any(
            same_term(term, x) for ts in pending.values() for x in ts)
        if already:
            notes.append(f"{term} is already on your resume")
            continue
        if not editable:
            manual.append({"term": term, "latex": "\\textbullet{} " + plain_to_latex(term)})
            continue
        block = next((b for b in editable if b.id == a.line), None) or editable[0]
        pending.setdefault(block.id, []).append(term)
    ops = []
    for bid, terms in pending.items():
        block = doc.block(bid)
        base = rewritten.get(bid, block.text)
        items = skill_items(base) + terms
        ops.append(Op(op="rewrite", target=bid, text=skill_separator(block.text).join(items), evidence=["skills"],
                      reason=f"You told us you have {', '.join(terms)}.", source="model"))
        notes.append(f"added {', '.join(terms)} to {block.label or 'your skills'}")
    return ops, notes, manual, refused


async def chat_turn(
    source_tex: str, analysis: JobAnalysis, evidence: list[EvidenceItem], message: str, history: list[dict], focus: str | None,
    unbacked: list[str], accepted: list[Op], llm: LLMClient, current_tex: str | None = None, page_limit: int | None = None,
) -> dict:
    """Understand what the person said and do it.

    The model decides what a message means: that they have a skill, that they did work with it, that they
    haven't, or that they're asking something. Code then does it and checks it. The person's own words are the
    evidence, so nothing here can use a tool, number, name or outcome they didn't say.
    """
    doc = parse_resume(source_tex)
    thread = "\n".join([str(h.get("text", "")) for h in history if h.get("role") == "you"][-6:] + [message]).strip()
    item = answer_to_evidence(focus or "what you told us", thread, next_answer_number([e.id for e in evidence]))
    all_evidence = [*evidence, item]
    overlay = _accepted_overlay(doc, accepted)

    turn = await llm.complete(chat_system(doc.bullet_budget), chat_user(doc, overlay, analysis, unbacked, history, item.id, message, focus), ChatTurn)

    skill_ops, notes, manual, refused = _skill_ops(doc, accepted, turn.skills, item, unbacked)
    stated = [t for o in skill_ops for t in skill_items(o.text or "") if any(same_term(t, a.term) for a in turn.skills)]
    if stated:
        # what the person says they can do is theirs to say: it joins the skills they've confirmed
        known = next((e for e in all_evidence if e.id == "skills"), None)
        confirmed = EvidenceItem(id="skills", source="skill", title="Skills the candidate can defend in an interview", skills=[*(known.skills if known else []), *stated])
        all_evidence = [e for e in all_evidence if e.id != "skills"] + [confirmed]
    bullet_ops = normalize_ops(doc, [p.to_op() for p in turn.ops if p.op == "add"])
    checked = validate_ops([*skill_ops, *bullet_ops], ValidationContext(doc=doc, evidence=all_evidence, analysis=analysis))
    blocked = [*refused, *({"op": v.op.describe(), "rule": v.rule, "message": v.message, "text": v.op.text} for v in checked.violations)]

    # a separate project has no entry to borrow from: only what the person said counts
    stub = Answer(term=focus or (turn.handled[0] if turn.handled else "skill"), text=thread)
    snippets, asked = [], ""
    for pd in turn.projects:
        if pd.answer != item.id:
            continue
        info = _project_from_reply(stub, item, pd)
        if info is None:
            asked = "What is the project called, and roughly when did you do it?"
            continue
        source = "\n".join([item.text, info.name, ", ".join(info.tech), info.dates])
        good = [b for b in pd.bullets[:8] if check_standalone_bullet(b, source, doc.bullet_budget) is None]
        for b in pd.bullets[:8]:
            problem = check_standalone_bullet(b, source, doc.bullet_budget)
            if problem:
                blocked.append({"op": f"project {info.name}", "rule": problem[0], "message": problem[1], "text": b})
        if good:
            snippets.append(await _project_snippet(doc, analysis, stub, item, good, current_tex or source_tex, page_limit, info))

    valid = checked.valid
    match = lambda names: [next((u for u in unbacked if same_term(u, n)), n) for n in names]  # noqa: E731
    handled = match([*turn.handled, *(s.term for s in turn.skills), *turn.skipped])
    narrative = any(o.op == "add" for o in valid) or bool(snippets)  # work they described, worth keeping as context
    produced = bool(valid or snippets)
    if not (produced or turn.skipped or notes):
        handled = []  # a question or a remark changes nothing, so nothing is done with any skill
    reply = turn.reply.strip()
    if manual:
        names = ", ".join(m["term"] for m in manual)
        reply = (reply + " " if reply else "") + f"I couldn't edit your Skills lines automatically. Add {names} to your Skills section in Overleaf; the code is below."
    if asked and not reply:
        reply = asked
    if turn.skills and not (skill_ops or manual):
        # the model said it added something; nothing was, so say what actually happened
        why = "; ".join(dict.fromkeys([*notes, *(b["message"] for b in refused)])) or "there was nothing new to add"
        reply = f"I didn't change your resume: {why}."
    return {
        "reply": reply or ("Done." if produced else "Tell me a little more about what you'd like on your resume."),
        "ops": [o.model_dump() for o in valid],
        "changes": describe_changes(doc, valid, analysis),
        "projects": snippets,
        "manual": manual,
        "blocked": blocked,
        "skipped": match(turn.skipped),
        "handled": list(dict.fromkeys(handled)) if not (asked or turn.needs_more) else [],
        "needs_more": bool(turn.needs_more or asked),
        "notes": notes,
        "stored": narrative,
        "evidence": [item.model_dump()] if narrative else [],
        "skills_confirmed": list(dict.fromkeys(t for o in valid if o.op == "rewrite" for t in skill_items(o.text or "") if any(same_term(t, a.term) for a in turn.skills))),
    }

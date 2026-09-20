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
from ..ats.health import health_score, lint_source, parse_health
from ..ats.quality import quality_report
from ..ats.recommend import recommendations
from ..ats.terms import contains_term, count_term, same_term
from ..compile.compile import CompileResult, UnsafeLatexError, compile_async, detect_engine, tex_available
from ..latex.apply import ApplyError, apply_ops
from ..latex.parse import ParsedResume, parse_resume
from ..learn.arms import ARMS
from ..learn.bandit import Bandit, context_key
from ..learn.style import StyleMemory
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import ANALYZE_SYSTEM, analyze_user, draft_system, draft_user, plan_system, plan_user, retry_user
from ..llm.schemas import Draft, Plan
from ..ops import Op
from ..reward.reward import RewardInput, reward
from ..evidence.answers import answer_to_evidence, next_answer_number
from ..types import Answer, EvidenceItem, JobAnalysis
from ..validate.validate import ValidationContext, Violation, validate_ops

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


def normalize_ops(doc: ParsedResume, ops: list[Op]) -> list[Op]:
    """Small, safe fixes to model output: a skills line's text shouldn't repeat its label."""
    for op in ops:
        if op.op == "rewrite" and op.text:
            b = doc.block(op.target)
            if b and b.kind == "skills" and b.label:
                op.text = re.sub(r"^\s*\**\s*" + re.escape(b.label) + r"\s*\**\s*:\s*\**\s*", "", op.text, flags=re.IGNORECASE)
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
        "pdf": base64.b64encode(compiled.pdf).decode() if compiled and compiled.ok and compiled.pdf else None,
        "page_limit": page_limit,
        "filename": suggested_filename(doc, analysis),
        "engine": detect_engine(doc.source),
        "usage": {"provider": llm.provider, "model": llm.model, "input_tokens": llm.usage.input_tokens, "output_tokens": llm.usage.output_tokens, "calls": llm.usage.calls},
        "warnings": warnings + best.warnings,
    }
    before_d, after_d = before.to_dict(), best.metrics.to_dict()
    result["ats"] = {"before": ats_score(before_d), "after": ats_score(after_d)}
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
        warnings.append("The edited file didn't compile: " + (compiled.errors[0].message if compiled.errors else "unknown error"))
    new_doc = parse_resume(new_tex)
    metrics, cov = measure(new_doc, analysis, compiled)
    limit = page_limit or 1
    if compiled and compiled.ok and compiled.pages > limit:
        warnings.append(f"The result is {compiled.pages} pages; the limit is {limit}. Revert an added bullet or keep a page-fit drop.")
    return {
        "tex": new_tex,
        "pdf": base64.b64encode(compiled.pdf).decode() if compiled and compiled.ok and compiled.pdf else None,
        "after": metrics.to_dict(),
        "coverage": [c.to_dict() for c in cov],
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


async def answer_gaps(
    source_tex: str,
    analysis: JobAnalysis,
    evidence: list[EvidenceItem],
    answers: list[Answer],
    accepted: list[Op],
    llm: LLMClient,
    emit: Emit = _noop,
) -> dict:
    """Turn the person's own words into checked bullets. One model call covers every answer.

    Nothing is applied or compiled here: the caller shows the drafted changes, the person accepts,
    and the existing rebuild applies them together with the ones already accepted.

    The drafted operations keep source="model". That is deliberate and load-bearing: source="user"
    skips every fabrication check, which is right for text a person typed and wrong for text a model
    wrote from their answer. Here the answer is the evidence, so a tool or number that isn't in what the
    person said is rejected like any other invention.
    """
    doc = parse_resume(source_tex)
    stored = [answer_to_evidence(a.term, a.text, next_answer_number([e.id for e in evidence]) + i) for i, a in enumerate(answers)]
    all_evidence = [*evidence, *stored]
    overlay = _accepted_overlay(doc, accepted)
    accepted_targets = {o.target for o in accepted}

    system = draft_system(doc.bullet_budget)
    base = draft_user(doc, overlay, all_evidence, list(zip(answers, stored)), analysis)
    vctx = ValidationContext(doc=doc, evidence=all_evidence, analysis=analysis)

    await emit(_event("draft", "start", f"Writing {len(answers)} bullet{'s' if len(answers) != 1 else ''} from what you told us"))
    message, blocked, followups, ops = base, [], [], []
    for attempt in range(1, MAX_DRAFT_RETRIES + 2):
        draft = await llm.complete(system, message, Draft)
        ops = normalize_ops(doc, [p.to_op() for p in draft.ops])
        followups = [f.model_dump() for f in draft.followups]
        result = validate_ops(ops, vctx)
        blocked = [{"attempt": attempt, "op": v.op.describe(), "rule": v.rule, "message": v.message, "text": v.op.text, "retried": attempt <= MAX_DRAFT_RETRIES}
                   for v in result.violations]
        if not result.violations or attempt > MAX_DRAFT_RETRIES:
            break
        message = retry_user(base, [o.model_dump() for o in ops], [f"{v.op.describe()}: {v.message}" for v in result.violations])

    valid = result.valid
    # a new bullet may not land on a block the person already changed: the newer suggestion replaces it
    superseded = [o.target for o in valid if o.target in accepted_targets and o.op != "add"]
    changes = describe_changes(doc, valid, analysis)
    await emit(_event("draft", "done", f"{len(valid)} bullet{'s' if len(valid) != 1 else ''} ready to review"))
    return {
        "ops": [o.model_dump() for o in valid],
        "changes": changes,
        "blocked": blocked,
        "followups": followups,
        "superseded": superseded,
        "evidence": [e.model_dump() for e in stored],
    }

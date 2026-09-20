"""What a change is worth, in ATS points.

The result page needs to say "add PyTorch: up to +11%" before anything has been written, and "+4.4%"
beside a change the model already made. Both come from the same place: the weights the reward already
uses, so there is one definition of the score in the codebase rather than two that drift apart.

A gain is an estimate. The real number arrives when the resume is rebuilt and measured.
"""

from __future__ import annotations

from ..ops import Op
from ..reward.reward import FULL_PAGE, WEIGHTS
from ..types import JobAnalysis
from .coverage import CONTEXT_SCORE, LISTED_SCORE, zones_after
from .terms import count_term

# What a keyword is worth where it sits: in a bullet, only in the skills list, or absent.
STATUS_SCORE = {"missing": 0.0, "listed": LISTED_SCORE, "context": CONTEXT_SCORE}


def ats_score(metrics: dict) -> float:
    """One 0..1 number for a set of measurements, using the reward's own weights.

    Deliberately not gated on page count, unlike reward(): a two-page resume still has a real keyword
    score, and this number is for showing people and for comparing before with after.
    """
    health = metrics.get("health")
    fill = metrics.get("page_fill")
    parts = {
        "must_have": metrics.get("must_have", 0.0),
        "nice_to_have": metrics.get("nice_to_have", 0.0),
        "title": metrics.get("title", 0.0),
        "parse_health": 1.0 if health is None else health,
        "page_fill": 1.0 if fill is None else min(1.0, fill / FULL_PAGE),
        "bullet_quality": metrics.get("quality", 0.5),
    }
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4)


def term_gain(analysis: JobAnalysis, term: str, frm: str = "missing", to: str = "context") -> float:
    """The ATS points gained by moving one job keyword from one place to another.

    A must-have is worth `0.40 * its weight / the weight of all must-haves`, so a central skill in a
    short list is worth more than a passing mention in a long one.
    """
    for t, must in analysis.terms():
        if t.term != term:
            continue
        group = [x for x, m in analysis.terms() if m == must]
        total = sum(x.weight for x in group)
        if not total:
            return 0.0
        share = WEIGHTS["must_have"] if must else WEIGHTS["nice_to_have"]
        return round(share * t.weight * (STATUS_SCORE[to] - STATUS_SCORE[frm]) / total, 4)
    return 0.0


def quality_gain(before: float, after: float) -> float:
    """The points gained by writing the bullets better."""
    return round(WEIGHTS["bullet_quality"] * (after - before), 4)


def per_change_gains(doc, ops: list[Op], analysis: JobAnalysis) -> list[dict]:
    """For each operation in turn: the job terms it brings in, and what that is worth.

    Walked in order with a running picture of the resume, so a keyword added by two changes is
    credited to the first one only and the figures can be added up without double counting. A change
    that removes the last mention of a term scores negative.
    """
    out: list[dict] = []
    applied: list[Op] = []
    before_context, before_listed = zones_after(doc, [])
    for op in ops:
        after_context, after_listed = zones_after(doc, [*applied, op])
        terms: list[str] = []
        gain = 0.0
        for t, _must in analysis.terms():
            was = _status(before_context, before_listed, t.term)
            now = _status(after_context, after_listed, t.term)
            if was == now:
                continue
            gain += term_gain(analysis, t.term, was, now)
            if STATUS_SCORE[now] > STATUS_SCORE[was]:
                terms.append(t.term)
        out.append({"terms": terms, "gain": round(gain, 4)})
        applied.append(op)
        before_context, before_listed = after_context, after_listed
    return out


def _status(context: str, listed: str, term: str) -> str:
    if count_term(context, term):
        return "context"
    return "listed" if count_term(listed, term) else "missing"


def gap_gains(analysis: JobAnalysis, gaps: list[dict], keywords: list[dict]) -> list[dict]:
    """What each unbacked job keyword would be worth if the person could back it.

    This is what the "needs your input" panel offers: the terms nothing in their context supports,
    most valuable first, so they know which one is worth writing a sentence about.
    """
    where = {k.get("term"): k.get("after", "missing") for k in keywords}
    out = []
    for g in gaps:
        if g.get("status") != "missing":
            continue
        term = g.get("term", "")
        frm = where.get(term, "missing")
        gain = term_gain(analysis, term, frm, "context")
        if gain <= 0:
            continue
        out.append({"term": term, "must": bool(g.get("must")), "weight": g.get("weight", 1), "gain": gain, "from": frm})
    out.sort(key=lambda x: -x["gain"])
    return out

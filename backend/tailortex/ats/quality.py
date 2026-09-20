"""General resume quality: the things that raise a score on any job, not just this one.

Keyword coverage answers "does this resume match that posting". These checks answer "is this a
well-written resume at all" — does a bullet say what changed, does it open with a verb doing work,
does it carry a number, is it the right length, is it in the third person and the past tense.

They are written up for people in docs/ATS.md, given to the model as prompts.ATS_RULES, and measured
here so the tailoring can be scored on them (reward/reward.py weights this at 0.10) and so the person
can be told what to fix.

Everything here reads the parsed LaTeX alone. Unlike parse_health, no PDF is needed, so a resume that
doesn't compile still gets useful feedback.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..latex.parse import Block, ParsedResume
from ..validate.validate import metrics
from .health import EMAIL_RE, Check, _has_phone, health_score

PASS = 0.8  # a graded check reads as "ok" at or above this
MIN_BULLET = 60  # shorter than this and a bullet has no room for a result
# A fixed ceiling, not doc.bullet_budget: that budget is 1.15x the longest bullet already in the
# template, so measuring against it would let a bullet raise its own ceiling and never read as long.
# Past ~240 characters a bullet runs to three lines and stops being skimmable.
MAX_BULLET = 240
TARGET_QUANT = 0.5  # half the bullets carrying a number is a good resume; full marks there

# Verbs a resume opens with. Used as a positive signal; anything ending in -ed counts too, because
# no list of English verbs is ever complete ("Containerized", "Dockerized", "Backfilled").
STRONG_VERBS = frozenset("""
built designed developed created implemented launched shipped delivered deployed released
led managed directed coordinated organised organized mentored trained supervised founded
improved increased raised boosted grew doubled tripled accelerated optimised optimized
reduced cut lowered decreased eliminated removed saved shortened simplified streamlined
migrated rewrote refactored redesigned rebuilt replaced modernised modernized ported
automated scripted integrated connected consolidated standardised standardized
scaled extended expanded generalised generalized parallelised parallelized
analysed analyzed measured modelled modeled forecast investigated diagnosed debugged
fixed resolved patched hardened secured stabilised stabilized
wrote authored documented published presented proposed negotiated won achieved earned
added introduced established initiated started drove spearheaded championed
tested validated verified benchmarked profiled instrumented monitored
collaborated partnered advised supported enabled
""".split())

# Openers that waste the most-read words on the line.
WEAK_OPENERS = (
    re.compile(r"^\s*(responsible|accountable)\s+for\b", re.I),
    re.compile(r"^\s*(worked|helped|assisted|participated|involved|contributed)\b", re.I),
    re.compile(r"^\s*(duties|responsibilities|tasks)\b", re.I),
    re.compile(r"^\s*(was|were|am|is|are)\b", re.I),
    re.compile(r"^\s*[A-Za-z]+ing\b"),  # a gerund: "Building a service that..."
    re.compile(r"^\s*(a|an|the)\b", re.I),
)

FIRST_PERSON_I = re.compile(r"\b(I|I'm|I've|I'd)\b")  # capitalised only: "i-node" isn't first person
FIRST_PERSON_WORDS = re.compile(r"\b(my|me|we|we're|we've|our|us)\b", re.I)


def _first_person(text: str) -> bool:
    return bool(FIRST_PERSON_I.search(text) or FIRST_PERSON_WORDS.search(text))
HOW_CLAUSE = re.compile(r"\b(by|using|with|through|via|leveraging|based on)\b", re.I)
# An outcome, however it's phrased: ", ending the missed run", "that removed race conditions",
# "which cut latency", "resulting in", "so that". Resumes phrase results in all of these ways.
RESULT_CLAUSE = re.compile(
    r",\s*\w+ing\b"
    r"|\b(?:that|which|who)\s+\w+(?:ed|s)\b"
    r"|\b(?:resulting in|so that|leading to|to (?:cut|reduce|support|serve|enable))\b"
    r"|\b(?:enabling|allowing|cutting|reducing|increasing|raising|saving|improving|eliminating|unblocking|ending)\b",
    re.I,
)
PRESENT_HEADING = re.compile(r"\b(present|current|now|ongoing)\b", re.I)
# Jan 2024 - Mar 2025, 01/2024-03/2025, 2024 - 2025, May 2024 - Present
DATE_RANGE = re.compile(
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}|\d{1,2}/\d{4}|\d{4})"
    r"\s*(?:-|–|—|to)\s*"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}|\d{1,2}/\d{4}|\d{4}|present|current|now)",
    re.I,
)
# A project often carries one year rather than a range, which is still a date.
SINGLE_DATE = re.compile(r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*)?(?:19|20)\d{2}\b", re.I)
_MONTH_YEAR = re.compile(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}", re.I)
_NUMERIC = re.compile(r"\d{1,2}/\d{4}")
# Layout commands that scramble the reading order when text is extracted.
BAD_LAYOUT = re.compile(r"\\begin\{(tabularx|longtable|multicols|paracol|wrapfigure|tcolorbox)\}|\\begin\{(minipage|tabular\*?)\}", re.I)
# Nearly every resume template lays out one heading row with a two-column tabular; that's harmless.
# What breaks extraction is a table long enough to hold the content itself.
LAYOUT_SPAN = 400


@dataclass
class Finding:
    """One block that fails a check, so the person can be shown exactly what to change."""

    check: str
    block_id: str
    text: str
    hint: str

    def to_dict(self) -> dict:
        return asdict(self)


def _bullets(doc: ParsedResume) -> list[Block]:
    return [b for s in doc.sections if not s.locked for e in s.entries for b in e.bullets if not b.locked]


def _prose(doc: ParsedResume) -> list[Block]:
    """Bullets plus the summary: everything written in sentences."""
    summaries = [b for s in doc.sections for b in s.blocks if b.kind == "summary"]
    return _bullets(doc) + summaries


def result_metrics(text: str) -> list[tuple[str, float, str]]:
    """Numbers that read as an outcome, not as a version or a language edition.

    `validate.metrics` is deliberately greedy: it decides what a bullet may not invent, so it counts
    everything. Here the bias is the other way round — "Python 3" and "Django 4.2" say nothing about
    impact, while "40%", "900ms", "1,200 merchants" do.
    """
    out = []
    for surface, value, cls in metrics(text, words=False):
        if cls != "n":  # a percentage, a duration, a size, money, a multiple
            out.append((surface, value, cls))
        elif value >= 10:  # a plain count only reads as a result once it's a quantity
            out.append((surface, value, cls))
    return out


def _first_word(text: str) -> str:
    m = re.match(r"\s*\**\s*([A-Za-z][\w'-]*)", text.replace("**", ""))
    return m.group(1) if m else ""


def _graded(cid: str, label: str, good: int, total: int, detail: str, weight: float) -> Check:
    score = good / total if total else 1.0
    return Check(id=cid, label=label, ok=score >= PASS, detail=detail.format(good=good, total=total, bad=total - good), weight=weight, score=round(score, 4))


def quality_checks(doc: ParsedResume) -> list[Check]:
    """How well the resume is written, independent of any job.

    A check with nothing to measure is left out rather than failed: a resume with no experience
    section shouldn't be marked down for having no dates.
    """
    checks: list[Check] = []
    bullets = _bullets(doc)
    prose = _prose(doc)

    if bullets:
        strong = sum(1 for b in bullets if _opens_strongly(b.text))
        checks.append(_graded("action_verb", "Bullets open with a strong verb", strong, len(bullets),
                              "{bad} of {total} bullets start weakly, with wording like \u201cResponsible for\u201d.", 2.0))

        quantified = sum(1 for b in bullets if result_metrics(b.text))
        rate = quantified / len(bullets)
        score = min(1.0, rate / TARGET_QUANT)
        checks.append(Check("quantified", "Results are quantified", score >= PASS,
                            f"{quantified} of {len(bullets)} bullets carry a number. Aim for about half.", 2.0, round(score, 4)))

        structured = sum(1 for b in bullets if _has_structure(b.text))
        checks.append(_graded("structure", "Bullets say what changed", structured, len(bullets),
                              "{bad} of {total} bullets stop at the task without saying how or what came of it.", 1.5))

        right_length = sum(1 for b in bullets if MIN_BULLET <= len(b.text.replace("**", "")) <= MAX_BULLET)
        checks.append(_graded("length", "Bullets are a workable length", right_length, len(bullets),
                              f"{{bad}} of {{total}} bullets are outside {MIN_BULLET}-{MAX_BULLET} characters.", 1.0))

        openers = [_first_word(b.text).lower() for b in bullets if _first_word(b.text)]
        overused = {w for w in openers if openers.count(w) > 2}
        varied = sum(1 for w in openers if w not in overused)
        checks.append(_graded("verb_variety", "Opening verbs vary", varied, len(openers) or 1,
                              f"{', '.join(sorted(overused)) or 'No verb'} repeated more than twice.", 0.5))

    if prose:
        third = sum(1 for b in prose if not _first_person(b.text))
        checks.append(_graded("third_person", "Written without \u201cI\u201d or \u201cwe\u201d", third, len(prose),
                              "{bad} of {total} lines use the first person; resumes drop the subject.", 1.5))

    tensed, total_tensed = _tense_agreement(doc)
    if total_tensed:
        checks.append(_graded("tense", "Tense is consistent", tensed, total_tensed,
                              "{bad} of {total} bullets don't match the tense of the role they sit under.", 1.0))

    dated, total_dated = _date_coverage(doc)
    if total_dated:
        checks.append(_graded("dates", "Roles and projects are dated", dated, total_dated,
                              "{bad} of {total} entries have no readable date range, or mix date formats.", 1.5))

    if doc.header_text.strip():
        found = [bool(EMAIL_RE.search(doc.header_text)), _has_phone(doc.header_text), bool(re.search(r"linkedin|github|https?://|\.(dev|io|com)\b", doc.header_text, re.I))]
        checks.append(_graded("contact_source", "Contact details are in the header", sum(found), 3,
                              "An email, a phone number and one profile link should be findable at the top.", 1.5))

    bad_layout = _layout_problems(doc.masked)
    checks.append(Check("layout", "Layout is single-column", not bad_layout,
                        "Tables, text boxes and multi-column blocks scramble the reading order an ATS extracts."
                        if bad_layout else "Nothing that would scramble the reading order.", 1.0))
    return checks


def _opens_strongly(text: str) -> bool:
    """Starts with a verb doing work, and not with a weak opener."""
    plain = text.replace("**", "")
    if any(rx.match(plain) for rx in WEAK_OPENERS):
        return False
    word = _first_word(plain).lower()
    return bool(word) and (word in STRONG_VERBS or (word.endswith("ed") and len(word) > 4))


def _layout_problems(masked: str) -> list[str]:
    """Layout blocks big enough to hold content, which is what scrambles an extracted reading order."""
    out = []
    for m in BAD_LAYOUT.finditer(masked):
        name = (m.group(1) or m.group(2) or "").strip("*")
        if name in ("tabularx", "longtable", "multicols", "paracol", "wrapfigure", "tcolorbox"):
            out.append(name)
            continue
        end = masked.find(f"\\end{{{name}", m.end())
        if end == -1 or end - m.end() > LAYOUT_SPAN:
            out.append(name)
    return out


def _has_structure(text: str) -> bool:
    """Says how it was done or what came of it, not just the task.

    Independent of how the bullet opens: a weak opener is already counted by `action_verb`, and
    charging the same sentence twice for one fault makes the score read as harsher than it is.
    """
    t = text.replace("**", "")
    return bool(HOW_CLAUSE.search(t) or RESULT_CLAUSE.search(t) or result_metrics(t))


def _tense_agreement(doc: ParsedResume) -> tuple[int, int]:
    """Bullets whose tense matches their entry: present only for a role marked Present or Current."""
    good = total = 0
    for s in doc.sections:
        if s.kind not in ("experience", "projects", "activities"):
            continue
        for e in s.entries:
            current = bool(PRESENT_HEADING.search(e.heading))
            for b in e.bullets:
                word = _first_word(b.text)
                if not word:
                    continue
                total += 1
                past = word.lower().endswith("ed") or word.lower() in STRONG_VERBS
                # "Leads"/"Builds" is present tense; fine for the role they still hold
                present = bool(re.match(r"^[A-Za-z]+s$", word)) and not word.lower().endswith("ss")
                good += 1 if (current or not present) and (past or not present) else 0
    return good, total


def _style_of(heading: str) -> str:
    return "month" if _MONTH_YEAR.search(heading) else "numeric" if _NUMERIC.search(heading) else "year"


def _date_coverage(doc: ParsedResume) -> tuple[int, int]:
    """Entries carrying a date, discounted where one section mixes date formats.

    Formats only need to agree within a section. A project dated "2024" beside a job dated
    "Aug. 2021 - May 2025" is ordinary resume style, not an inconsistency.
    """
    good = total = 0.0
    for s in doc.sections:
        if s.kind not in ("experience", "education", "projects") or not s.entries:
            continue
        headings = [e.heading for e in s.entries]
        dated = [h for h in headings if DATE_RANGE.search(h) or SINGLE_DATE.search(h)]
        consistent = len({_style_of(h) for h in dated}) <= 1
        good += len(dated) * (1.0 if consistent else 0.6)
        total += len(headings)
    return int(round(good)), int(total)


def quality_findings(doc: ParsedResume) -> list[Finding]:
    """The specific blocks behind the failing checks, so the page can quote them."""
    out: list[Finding] = []
    for b in _bullets(doc):
        plain = b.text.replace("**", "")
        if not _opens_strongly(plain):
            out.append(Finding("action_verb", b.id, plain, f"Open with what you did: Built, Led, Cut, Migrated \u2014 not \u201c{' '.join(plain.split()[:2])}\u2026\u201d."))
        if not result_metrics(plain):
            out.append(Finding("quantified", b.id, plain, "Add the number you already know: how much faster, how many users, how much saved."))
        elif not _has_structure(plain):
            out.append(Finding("structure", b.id, plain, "Say how you did it or what changed as a result."))
        if len(plain) < MIN_BULLET:
            out.append(Finding("length", b.id, plain, "Too short to carry a result; say what changed."))
        elif len(plain) > MAX_BULLET:
            out.append(Finding("length", b.id, plain, f"Over {MAX_BULLET} characters, so it runs to three lines and stops being skimmable."))
    for b in _prose(doc):
        if _first_person(b.text):
            out.append(Finding("third_person", b.id, b.text.replace("**", ""), "Drop the \u201cI\u201d or \u201cwe\u201d; resumes are written without the subject."))
    return out


def quality_report(doc: ParsedResume) -> tuple[float, list[Check], list[Finding]]:
    """(score 0..1, the checks, the blocks that failed them)."""
    checks = quality_checks(doc)
    return round(health_score(checks), 4), checks, quality_findings(doc)

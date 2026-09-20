"""Finding what a person's own material already shows, in words the job doesn't use.

A job asks for "Generative AI"; the resume says "RAG-powered LLM pipeline" and "7-agent CrewAI system".
The words differ and the work is the same. Matching words alone calls that skill missing, so the tool
told the person to prove something their resume already demonstrates, and told the model not to write it.

So for each job skill that isn't written out, this searches the person's own material by meaning (the
resume's bullets plus everything in their context, which is theirs alone), asks the model whether the
best matches really show it, and accepts the answer only if the model quotes the person's own words
back exactly.

Two rules keep it honest:
- a tool, library or product (TensorFlow, PyTorch, Kubernetes...) is supported only if the material
  *names* it: a related tool proves nothing;
- a broad field (machine learning, generative AI, statistics...) may be shown by describing the work.

Every accepted answer carries its quote and where it came from, so the person can see the reasoning.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass

from ..ats.coverage import Gap
from ..ats.terms import contains_term, same_term
from ..latex.parse import ParsedResume
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import SUPPORT_SYSTEM, support_user
from ..llm.schemas import SupportReply
from ..types import EvidenceItem, JobAnalysis

log = logging.getLogger("tailortex")

TOP_K = 4  # passages shown to the model per skill
MIN_QUOTE = 12  # a quote shorter than this can't show much

# Fields and concepts that a description of the work can show. Everything else (tools, libraries, languages,
# products) has to be named.
CONCEPTS = (
    "machine learning", "deep learning", "generative ai", "artificial intelligence", "computer vision",
    "natural language processing", "nlp", "data science", "statistics", "algorithms", "data structures",
    "object-oriented programming", "oop", "system design", "distributed systems", "microservices",
    "api design", "software engineering", "software development", "testing", "agile", "data analysis",
    "data engineering", "prompt engineering", "large language models", "llms", "llm", "rag",
    "retrieval augmented generation", "multi-agent", "mlops", "reinforcement learning", "recommendation systems",
)


@dataclass
class Support:
    term: str
    passage_id: str
    origin: str  # what it was found in, in words: "your resume, Multimodal Interview Analysis System"
    quote: str
    how: str  # "named" or "described"
    source: str  # the evidence source it came from: github, linkedin, fact, or resume
    scope: str | None  # the resume entry it was found in, or None for context
    url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def is_concept(term: str) -> bool:
    return any(same_term(term, c) for c in CONCEPTS)


def _flat(text: str) -> str:
    """Comparable text: no bold markers, one space, lower case."""
    return re.sub(r"\s+", " ", text.replace("**", "")).strip().lower()


def quote_is_real(quote: str, passage_text: str) -> bool:
    """The model may not paraphrase: its quote has to be in the passage, word for word."""
    q = _flat(quote).strip(" .…\"'")
    return len(q) >= MIN_QUOTE and q in _flat(passage_text)


@dataclass
class _Passage:
    id: str
    origin: str
    text: str
    source: str
    scope: str | None
    url: str | None


def _passages(doc: ParsedResume, evidence: list[EvidenceItem]) -> list[_Passage]:
    """Everything that is the person's own: their context entries, and the bullets of their resume."""
    out = [_Passage(e.id, f"your {e.source} context, {e.title[:60] or e.id}", f"{e.title}. {e.text}".strip(". "), e.source, e.scope, e.url)
           for e in evidence if e.source != "skill" and (e.text or e.title)]
    for s in doc.sections:
        for e in s.entries:
            heading = e.heading.split("|")[0].strip()[:60] or e.id
            for b in e.bullets:
                out.append(_Passage(f"resume:{b.id}", f"your resume, {heading}", b.text.replace("**", ""), "resume", e.id, None))
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def find_support(
    doc: ParsedResume, analysis: JobAnalysis, gaps: list[Gap], evidence: list[EvidenceItem], llm: LLMClient, embed_fn=None,
) -> list[Support]:
    """Which job skills that aren't written out does the person's own material show? One model call."""
    missing = [g for g in gaps if g.status == "missing"]
    passages = _passages(doc, evidence)
    if not missing or not passages:
        return []
    if embed_fn is None:
        from ..db.embed import embed as embed_fn  # the same local model that indexes their context

    try:
        vectors = await embed_fn([p.text for p in passages] + [f"experience with {g.term}" for g in missing])
    except Exception:  # an unavailable embedder means no semantic help, not a failed tailoring
        log.exception("Couldn't embed the material for semantic support")
        return []
    pvec, tvec = vectors[: len(passages)], vectors[len(passages):]

    cases, candidates = [], {}
    for g, tv in zip(missing, tvec):
        ranked = sorted(range(len(passages)), key=lambda i: -_cosine(tv, pvec[i]))[:TOP_K]
        chosen = [passages[i] for i in ranked]
        candidates[g.term] = {p.id: p for p in chosen}
        cases.append((g.term, [(p.id, p.origin, p.text) for p in chosen]))

    try:
        reply = await llm.complete(SUPPORT_SYSTEM, support_user(cases), SupportReply)
    except LLMError:
        return []  # the tailoring goes ahead without it

    found: dict[str, Support] = {}
    for item in reply.terms:
        term = next((g.term for g in missing if same_term(g.term, item.term)), None)
        p = candidates.get(term or "", {}).get(item.passage)
        if not (term and item.supported and p) or term in found:
            continue
        if not quote_is_real(item.quote, p.text):
            continue  # paraphrased or invented: not accepted
        if item.how == "named" or not is_concept(term):
            if not contains_term(item.quote, term):
                continue  # a tool has to be named, and it wasn't
        found[term] = Support(term, p.id, p.origin, item.quote.strip(), item.how, p.source, p.scope, p.url)
    return list(found.values())


def derive_evidence(supports: list[Support], start: int = 1) -> list[EvidenceItem]:
    """The findings as evidence the planner can cite: the person's own quote, with the skill it shows.

    Something found in the resume keeps its scope, so it backs bullets only in the entry it came from.
    """
    out = []
    for i, s in enumerate(supports, start):
        out.append(EvidenceItem(
            id=f"inf{i}",
            source="fact" if s.source == "resume" else s.source,  # type: ignore[arg-type]
            title=f"{s.term}, from {s.origin}"[:120],
            text=s.quote,
            skills=[s.term],
            url=s.url,
            scope=s.scope if s.source == "resume" else None,
        ))
    return out

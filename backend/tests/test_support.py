"""A skill can be shown in other words than the job uses. These tests are the honesty rules of finding it.

The model may say a passage shows a skill, but its answer is only accepted if it quotes the person's own words back
exactly, and a tool or library counts only if the material names it. A related tool proves nothing.
"""

import asyncio
from pathlib import Path

import pytest
from conftest import MockLLM

from tailortex.ats.coverage import gap_analysis
from tailortex.evidence import support as sup
from tailortex.evidence.support import derive_evidence, find_support, is_concept, quote_is_real
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op
from tailortex.types import EvidenceItem, JobAnalysis, JobTerm
from tailortex.validate.validate import ValidationContext, validate_ops

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
BULLET = "Wrote integration tests with pytest that raised coverage of the payouts service from 41% to 78%"
GITHUB = EvidenceItem(id="gh-fraud", source="github", title="fraud-detector", text="Trained a classifier on labelled transactions to flag fraud, evaluated with precision and recall.", skills=["Python"])


async def fake_embed(texts):
    """Every text the same distance from every other: retrieval is not what these tests are about."""
    return [[1.0, 0.0, 0.0] for _ in texts]


def ask(terms, reply, evidence=None):
    doc = parse_resume(JAKE)
    analysis = JobAnalysis(title="Engineer", must_have=[JobTerm(term=t, weight=2) for t in terms])
    llm = MockLLM({}, [{"ops": []}])
    llm.support = {"terms": reply}
    gaps = gap_analysis(doc, analysis, evidence or [])
    return asyncio.run(find_support(doc, analysis, gaps, evidence or [], llm, fake_embed)), llm


def said(term, passage, quote, how="described", supported=True):
    return {"term": term, "supported": supported, "passage": passage, "quote": quote, "how": how}


def test_a_broad_field_can_be_shown_by_describing_the_work():
    found, llm = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest")])
    assert [s.term for s in found] == ["Testing"] and llm.support_calls == 1
    s = found[0]
    assert s.how == "described" and s.scope == "s1.e0" and s.source == "resume" and "your resume" in s.origin


def test_a_quote_the_model_made_up_or_reworded_is_refused():
    assert quote_is_real("**Wrote** integration tests with pytest", BULLET)  # bold markers and case don't matter
    assert not quote_is_real("Built a comprehensive automated testing framework", BULLET)  # a paraphrase
    assert not quote_is_real("tests", BULLET)  # too short to show anything
    found, _ = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Designed an automated testing framework for the payouts team")])
    assert found == []


def test_a_tool_is_supported_only_if_the_material_names_it():
    """TensorFlow described in other words is not TensorFlow."""
    assert not is_concept("TensorFlow") and is_concept("Machine learning") and is_concept("Generative AI")
    described = said("TensorFlow", "gh-fraud", "Trained a classifier on labelled transactions to flag fraud")
    assert ask(["TensorFlow"], [described], [GITHUB])[0] == []
    claimed_named = said("TensorFlow", "gh-fraud", "Trained a classifier on labelled transactions to flag fraud", how="named")
    assert ask(["TensorFlow"], [claimed_named], [GITHUB])[0] == []  # the model saying "named" doesn't make it so
    # and a passage that really does name it never needs this step: the word match already finds it
    named = EvidenceItem(id="gh-nn", source="github", title="digits", text="Built a digit recogniser in TensorFlow using a small CNN.", skills=[])
    doc = parse_resume(JAKE)
    analysis = JobAnalysis(title="Engineer", must_have=[JobTerm(term="TensorFlow", weight=2)])
    assert [g.status for g in gap_analysis(doc, analysis, [named])] == ["evidence"]


def test_a_passage_the_model_was_not_shown_is_refused():
    found, _ = ask(["Testing"], [said("Testing", "made-up-id", "Wrote integration tests with pytest")])
    assert found == []


def test_unsupported_and_unasked_terms_are_ignored():
    found, _ = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest", supported=False),
                                 said("Rust", "resume:s1.e0.b2", "Wrote integration tests with pytest")])
    assert found == []


def test_nothing_missing_means_no_model_call():
    doc = parse_resume(JAKE)
    analysis = JobAnalysis(title="Engineer", must_have=[JobTerm(term="Python", weight=3)])  # already on the resume
    llm = MockLLM({}, [{"ops": []}])
    assert asyncio.run(find_support(doc, analysis, gap_analysis(doc, analysis, []), [], llm, fake_embed)) == [] and llm.support_calls == 0


def test_a_failing_embedder_or_model_means_no_help_not_a_failed_tailoring():
    doc = parse_resume(JAKE)
    analysis = JobAnalysis(title="Engineer", must_have=[JobTerm(term="Testing", weight=2)])

    async def broken(_texts):
        raise RuntimeError("model missing")

    llm = MockLLM({}, [{"ops": []}])
    assert asyncio.run(find_support(doc, analysis, gap_analysis(doc, analysis, []), [], llm, broken)) == []


def test_found_evidence_is_the_persons_own_quote_and_keeps_where_it_came_from():
    found, _ = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest")])
    [item] = derive_evidence(found)
    assert item.id == "inf1" and item.text == "Wrote integration tests with pytest" and item.skills == ["Testing"]
    assert item.source == "fact" and item.scope == "s1.e0"  # a resume finding is bound to its entry
    found, _ = ask(["Machine learning"], [said("Machine learning", "gh-fraud", "Trained a classifier on labelled transactions to flag fraud")], [GITHUB])
    [ctx_item] = derive_evidence(found)
    assert ctx_item.source == "github" and ctx_item.scope is None and ctx_item.url == GITHUB.url  # context keeps its own source rules


def test_something_found_in_one_entry_cannot_back_a_bullet_in_another():
    """A skill shown in one job can't be moved into another: the rule the whole tool stands on."""
    found, _ = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest")])
    evidence = derive_evidence(found)
    doc = parse_resume(JAKE)
    ctx = ValidationContext(doc=doc, evidence=evidence)
    inside = Op(op="rewrite", target="s1.e0.b0", evidence=["inf1"], text="Developed REST endpoints in Python and Flask with Testing for merchant onboarding, used by 1,200 merchants")
    elsewhere = Op(op="rewrite", target="s1.e1.b0", evidence=["inf1"], text="Built an internal dashboard in React and TypeScript with Testing that replaced a weekly spreadsheet report for 30 analysts")
    assert validate_ops([inside], ctx).valid
    r = validate_ops([elsewhere], ctx)
    assert not r.valid and r.violations[0].rule == "evidence_scope" and "s1.e0" in r.violations[0].message


def test_the_pipeline_uses_what_was_found_and_shows_it(monkeypatch):
    from test_pipeline_learn import ANALYSIS
    from tailortex.pipeline.tailor import TailorInput, tailor

    monkeypatch.setenv("TAILORTEX_EMBEDDINGS", "hashed")
    monkeypatch.setattr(sup, "TOP_K", 100)
    analysis = {**ANALYSIS, "must_have": [{"term": "Testing", "weight": 3}, {"term": "Python", "weight": 3}], "nice_to_have": []}
    llm = MockLLM(analysis, [{"ops": []}])
    llm.support = {"terms": [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest")]}
    r = asyncio.run(tailor(TailorInput(tex=JAKE, jd="Testing and Python", compile_pdf=False), llm))
    assert llm.support_calls == 1
    assert [i["term"] for i in r["inferred"]] == ["Testing"] and r["inferred"][0]["quote"] == "Wrote integration tests with pytest"
    assert r["inferred_evidence"][0]["scope"] == "s1.e0"
    # the model was told about it as evidence, not as MISSING, and told where it may be used
    plan_prompt = next(u for _s, u in llm.prompts if "<job>" in u and "<evidence>" in u)
    assert "Testing [EVIDENCE: inf1]" in plan_prompt and "only usable in bullets of that entry" in plan_prompt
    assert "Testing" not in [g["term"] for g in r["gains"]["gaps"]]  # so the person isn't asked to prove it


def test_a_field_outside_software_can_be_shown_by_describing_the_work():
    """No list of concepts could cover every trade, so the model says whether a term is a named tool or an
    area of practice, and a term it calls a field may be shown in the person's own different words."""
    nurse = EvidenceItem(id="n1", source="fact", title="Ward work",
                         text="Taught families how to care for surgical wounds at home before discharge.")
    found, _ = ask(["Patient Education"], [dict(said("Patient Education", "n1", "Taught families how to care for surgical wounds at home"), kind="field")], [nurse])
    assert [(f.term, f.how) for f in found] == [("Patient Education", "described")]


def test_a_named_thing_outside_software_still_has_to_be_named():
    """A different records system is not Epic, exactly as a different library is not PyTorch."""
    nurse = EvidenceItem(id="n1", source="fact", title="Ward work",
                         text="Charted every handover in the ward's electronic records system.")
    found, _ = ask(["Epic"], [dict(said("Epic", "n1", "Charted every handover in the ward's electronic records system"), kind="tool")], [nurse])
    assert found == []


def test_a_model_that_says_nothing_about_the_kind_falls_back_to_the_old_rule():
    found, _ = ask(["Testing"], [said("Testing", "resume:s1.e0.b2", "Wrote integration tests with pytest")])
    assert [f.term for f in found] == ["Testing"]

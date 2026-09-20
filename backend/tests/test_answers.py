"""Asking the person for what their resume doesn't show, and writing from their answer without inventing.

The whole feature rests on one claim: a bullet written from someone's answer can only use what that
answer says. These tests are that claim, on the path that runs after the person types a sentence.
"""

import asyncio
from pathlib import Path

from conftest import MockLLM

from tailortex.evidence.answers import answer_to_evidence, is_answer, next_answer_number
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op
from tailortex.pipeline.tailor import answer_gaps
from tailortex.types import Answer, EvidenceItem, JobAnalysis, JobTerm

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()

ANALYSIS = JobAnalysis(
    title="ML Engineer",
    must_have=[JobTerm(term="PyTorch", weight=3), JobTerm(term="Python", weight=3), JobTerm(term="TensorFlow", weight=2)],
)
STORED = [EvidenceItem(id="n1", source="fact", title="note", text="Led the robotics club, 12 members")]
SENTENCE = "At Finch Payments I trained a PyTorch model that flags fraudulent transfers and cut manual review time by 30%"


def draft(ops=None, followups=None):
    return {"ops": ops or [], "followups": followups or []}


def run(plan, answers, accepted=None, evidence=None):
    llm = MockLLM({}, [plan])
    result = asyncio.run(answer_gaps(JAKE, ANALYSIS, evidence if evidence is not None else STORED, answers, accepted or [], llm))
    return result, llm


def test_an_answer_becomes_a_fact_a_bullet_may_cite_in_any_section():
    item = answer_to_evidence("PyTorch", SENTENCE, 1)
    assert item.id == "ans1" and item.source == "fact"  # `fact` is allowed in experience; `skill` never is
    assert "PyTorch" in item.skills and item.text == SENTENCE
    assert is_answer("ans1") and not is_answer("n1") and not is_answer("gh-repo")


def test_an_answer_that_never_names_the_skill_does_not_quietly_claim_it():
    item = answer_to_evidence("PyTorch", "I trained a neural network for a course project and it worked well", 1)
    assert "PyTorch" not in item.skills  # they were asked about it, but they didn't say it


def test_answer_ids_are_their_own_namespace_and_never_collide():
    assert next_answer_number(["n1", "n2", "gh-x"]) == 1
    assert next_answer_number(["n1", "ans1", "ans4"]) == 5


def test_an_answer_becomes_a_checked_bullet_citing_it():
    plan = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%",
                   "evidence": ["ans1"], "reason": "the job asks for PyTorch"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE, target="s1.e0")])
    assert len(result["ops"]) == 1 and not result["blocked"]
    op = result["ops"][0]
    assert op["op"] == "add" and op["evidence"] == ["ans1"] and "PyTorch" in op["text"] and "30%" in op["text"]
    assert result["evidence"][0]["id"] == "ans1"  # handed back so the caller can store it
    assert result["changes"][0]["gain"] > 0 and "PyTorch" in result["changes"][0]["terms"]


def test_a_tool_the_answer_never_named_is_blocked():
    """The no-invention guarantee under the new path: the answer says PyTorch, not TensorFlow."""
    plan = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained PyTorch and TensorFlow models that flag fraudulent transfers",
                   "evidence": ["ans1"], "reason": "x"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE, target="s1.e0")])
    assert result["ops"] == []
    assert any(b["rule"] == "invented_term" and "TensorFlow" in b["message"] for b in result["blocked"])


def test_a_number_that_is_not_in_the_answer_is_blocked():
    plan = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained a PyTorch model that cut manual review time by 80%",
                   "evidence": ["ans1"], "reason": "x"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE, target="s1.e0")])
    assert result["ops"] == []
    assert any(b["rule"] == "invented_number" and "80%" in b["message"] for b in result["blocked"])


def test_a_drafted_bullet_never_carries_the_person_typed_marker():
    """source="user" skips every fabrication check. Model-written text must never get it."""
    plan = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%",
                   "evidence": ["ans1"], "reason": "x"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE)])
    assert result["ops"] and all(o["source"] == "model" for o in result["ops"])


def test_a_bare_claim_returns_a_question_not_a_bullet():
    plan = draft(followups=[{"term": "PyTorch", "question": "What did you build with PyTorch, and what changed because of it?"}])
    result, _ = run(plan, [Answer(term="PyTorch", text="I know PyTorch quite well from my studies")])
    assert result["ops"] == [] and not result["blocked"]
    assert result["followups"] == [{"term": "PyTorch", "question": "What did you build with PyTorch, and what changed because of it?"}]


def test_many_answers_cost_one_model_call():
    """Free-tier keys allow about twenty requests a day per model, so answers are batched."""
    plan = draft([
        {"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
         "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%", "evidence": ["ans1"], "reason": "x"},
        {"op": "add", "target": "s1.e1", "after": "s1.e1.b0",
         "text": "Built a TensorFlow classifier for support tickets that routed 2,000 tickets a week", "evidence": ["ans2"], "reason": "x"},
    ])
    answers = [
        Answer(term="PyTorch", text=SENTENCE),
        Answer(term="TensorFlow", text="For the analytics team I built a TensorFlow classifier for support tickets that routed 2,000 tickets a week"),
    ]
    result, llm = run(plan, answers)
    assert llm.plan_calls == 1 and len(result["ops"]) == 2 and not result["blocked"]
    assert [e["id"] for e in result["evidence"]] == ["ans1", "ans2"]


def test_a_rejected_draft_gets_one_repair_pass_and_no_more():
    bad = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1", "text": "Trained PyTorch and Keras models for fraud detection",
                  "evidence": ["ans1"], "reason": "x"}])
    good = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%", "evidence": ["ans1"], "reason": "x"}])
    llm = MockLLM({}, [bad, good])
    result = asyncio.run(answer_gaps(JAKE, ANALYSIS, STORED, [Answer(term="PyTorch", text=SENTENCE)], [], llm))
    assert llm.plan_calls == 2 and len(result["ops"]) == 1  # the second try was accepted
    # and it never loops: a model that keeps inventing stops after the repair
    llm = MockLLM({}, [bad])
    result = asyncio.run(answer_gaps(JAKE, ANALYSIS, STORED, [Answer(term="PyTorch", text=SENTENCE)], [], llm))
    assert llm.plan_calls == 2 and result["ops"] == [] and result["blocked"]


def test_the_draft_sees_the_resume_as_the_person_already_changed_it():
    accepted = [Op(op="rewrite", target="s1.e0.b0", text="ALREADY ACCEPTED WORDING about merchant onboarding")]
    _, llm = run(draft(), [Answer(term="PyTorch", text=SENTENCE)], accepted=accepted)
    prompt = llm.prompts[0][1]
    assert "ALREADY ACCEPTED WORDING" in prompt and "Developed REST endpoints" not in prompt
    assert "ans1" in prompt and SENTENCE in prompt


def test_a_draft_that_lands_on_an_accepted_block_says_it_replaces_it():
    accepted = [Op(op="rewrite", target="s1.e0.b0", text="Developed REST APIs in Python and Flask for merchant onboarding, used by 1,200 merchants in the first quarter")]
    plan = draft([{"op": "rewrite", "target": "s1.e0.b0",
                   "text": "Developed REST endpoints in Python and Flask for merchant onboarding, used by 1,200 merchants in the first quarter",
                   "evidence": [], "reason": "x"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE)], accepted=accepted)
    assert result["superseded"] == ["s1.e0.b0"]


def test_an_answer_is_never_applied_or_compiled_by_the_draft():
    """Nothing changes until the person accepts: the draft returns operations, not a resume."""
    plan = draft([{"op": "add", "target": "s1.e0", "after": "s1.e0.b1",
                   "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%", "evidence": ["ans1"], "reason": "x"}])
    result, _ = run(plan, [Answer(term="PyTorch", text=SENTENCE)])
    assert "tex" not in result and "pdf" not in result


def test_accepted_answers_apply_through_the_ordinary_rebuild():
    from tailortex.pipeline.tailor import rebuild

    op = Op(op="add", target="s1.e0", after="s1.e0.b1",
            text="Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%", evidence=["ans1"], source="model")
    item = answer_to_evidence("PyTorch", SENTENCE, 1)
    out = asyncio.run(rebuild(JAKE, [op], ANALYSIS, [*STORED, item], compile_pdf=False))
    assert "PyTorch model that flags fraudulent transfers" in out["tex"] and not out["warnings"]
    # the same op without the answer as evidence is refused, so the answer really is what allows it
    refused = asyncio.run(rebuild(JAKE, [op], ANALYSIS, STORED, compile_pdf=False))
    assert "PyTorch model" not in refused["tex"] and refused["warnings"]
    # and the coverage moved: PyTorch is now shown in a bullet
    assert next(c for c in out["coverage"] if c["term"] == "PyTorch")["status"] == "context"

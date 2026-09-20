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


# --- a separate project: code to paste into Overleaf, since an entry can't be created ------------------------


from tailortex.latex.snippet import insert_project, project_block, project_style  # noqa: E402
from tailortex.types import ProjectInfo  # noqa: E402

FRAUD = ProjectInfo(name="Fraud Detector", dates="Jan 2026 - Apr 2026", tech=["PyTorch", "Python"])
FRAUD_TEXT = "For a course project I trained a PyTorch model in Python that flags fraudulent card transfers and cut manual review time by 30%"


def project_plan(bullets, answer="ans1"):
    return {"ops": [], "projects": [{"answer": answer, "bullets": bullets}], "followups": []}


GOOD_BULLETS = [
    "Trained a **PyTorch** model in **Python** that flags fraudulent card transfers",
    "Cut manual review time by **30%** by ranking the transfers most likely to be fraud",
]


def test_a_separate_project_becomes_latex_in_the_resumes_own_style_not_an_operation():
    result, llm = run(project_plan(GOOD_BULLETS), [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert result["ops"] == [] and len(result["projects"]) == 1 and llm.plan_calls == 1
    p = result["projects"][0]
    assert p["style"] == "jake" and "\\resumeProjectHeading" in p["latex"]  # the sample template writes projects this way
    assert "\\textbf{Fraud Detector}" in p["latex"] and "Jan 2026 -- Apr 2026" in p["latex"]  # an en dash is written --
    assert "\\resumeItem{Trained a \\textbf{PyTorch} model" in p["latex"] and "30\\%" in p["latex"]  # escaped by TailorTeX
    assert p["tex_with_project"].count("Fraud Detector") == 1 and p["where"] == "after your last project"


def test_a_hand_written_resume_gets_its_own_hfill_style():
    handwritten = JAKE.replace("\\resumeProjectHeading", "\\resumeSubheading")  # no Jake project macro to copy
    handwritten = (
        "\\documentclass{article}\n\\begin{document}\n\\section*{Projects}\n\\vspace{4pt}\n\\noindent\n"
        "\\textbf{Old Project} \\hfill 2024 \\\\\n\\textit{Tech: Python}\n\\begin{itemize}\n    \\item Built a tool in Python that saved 3 hours\n"
        "\\end{itemize}\n\\end{document}\n"
    )
    doc = parse_resume(handwritten)
    assert project_style(doc) == "hfill"
    block = project_block(doc, "Fraud Detector", "Jan 2026 - Apr 2026", ["PyTorch", "Python"], GOOD_BULLETS)
    assert block.splitlines()[:4] == ["\\vspace{4pt}", "\\noindent", "\\textbf{Fraud Detector} \\hfill Jan 2026 -- Apr 2026 \\\\", "\\textit{Tech: PyTorch, Python}"]
    merged, where = insert_project(doc, block)
    assert merged.index("Old Project") < merged.index("Fraud Detector") < merged.index("\\end{document}")


def test_the_project_code_cannot_break_the_file():
    """Names, dates and bullets are all user text, and all of it goes through the escaper."""
    doc = parse_resume(JAKE)
    nasty = project_block(doc, "R&D \\input{evil} 50% $x_y$", "2026 & 2027", ["C#", "a_b"], ["Used **C#** & 100% of the {budget} \\write18"])
    assert "\\input{evil}" not in nasty.replace("\\textbackslash", "") and "\\write18" not in nasty.replace("\\textbackslash", "")
    from tailortex.compile.compile import compile_latex, tex_available

    if tex_available():
        assert compile_latex(insert_project(doc, nasty)[0]).ok


def test_a_tool_the_person_never_mentioned_is_refused_in_a_project_bullet():
    plan = project_plan(["Trained **PyTorch** and **TensorFlow** models that flag fraudulent transfers"])
    result, _ = run(plan, [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert result["projects"] == []
    assert any(b["rule"] == "invented_term" and "TensorFlow" in b["message"] for b in result["blocked"])
    # and instead of silence, they are asked for more
    assert any("Fraud Detector" in f["question"] for f in result["followups"])


def test_a_number_the_person_never_gave_is_refused_in_a_project_bullet():
    result, _ = run(project_plan(["Cut manual review time by **80%** with a **PyTorch** model"]), [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert result["projects"] == [] and any(b["rule"] == "invented_number" and "80%" in b["message"] for b in result["blocked"])


def test_the_dates_they_typed_are_allowed_as_numbers_but_a_new_year_is_not():
    result, _ = run(project_plan(["Built a **PyTorch** model in **Python** during Jan 2026 - Apr 2026 to flag fraud"]),
                    [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert len(result["projects"]) == 1
    result, _ = run(project_plan(["Built a **PyTorch** model in **Python** in 2019 to flag fraud"]), [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert result["projects"] == []


def test_the_snippet_says_what_adding_the_project_is_worth_and_whether_it_still_fits():
    result, _ = run(project_plan(GOOD_BULLETS), [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    p = result["projects"][0]
    assert p["ats_after"] > p["ats_before"] and "PyTorch" in p["terms"]
    assert p["compiles"] in (True, None) and p["over_limit"] is False
    assert p["pages"] in (1, None) and p["page_limit"] >= 1


def test_an_operation_citing_a_project_answer_is_dropped_because_there_is_no_entry_to_add_to():
    plan = {"ops": [{"op": "add", "target": "s1.e0", "after": "s1.e0.b1", "evidence": ["ans1"], "reason": "x",
                     "text": "Trained a PyTorch model in Python that flags fraudulent card transfers"}],
            "projects": [{"answer": "ans1", "bullets": GOOD_BULLETS}], "followups": []}
    result, _ = run(plan, [Answer(term="PyTorch", text=FRAUD_TEXT, project=FRAUD)])
    assert result["ops"] == [] and len(result["projects"]) == 1


def test_an_answer_about_an_existing_job_and_one_about_a_new_project_can_share_one_call():
    plan = {"ops": [{"op": "add", "target": "s1.e0", "after": "s1.e0.b1", "evidence": ["ans1"], "reason": "x",
                     "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%"}],
            "projects": [{"answer": "ans2", "bullets": ["Built a **TensorFlow** classifier for support tickets that routed **2,000** tickets a week"]}], "followups": []}
    answers = [Answer(term="PyTorch", text=SENTENCE),
               Answer(term="TensorFlow", text="For the analytics team I built a TensorFlow classifier that routed 2,000 support tickets a week",
                      project=ProjectInfo(name="Ticket Router", dates="2025", tech=["TensorFlow"]))]
    result, llm = run(plan, answers)
    assert llm.plan_calls == 1 and len(result["ops"]) == 1 and len(result["projects"]) == 1
    assert result["evidence"][1]["title"] == "Project: Ticket Router"  # the project name travels with the stored answer

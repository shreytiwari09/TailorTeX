"""Do what the person says. They may have a skill and no project, name a skill the job never listed, say no, or ask a question.

The model works out what a message means; code does it and checks it. The person's own words are the evidence, so a skill
they state is theirs to state, and nothing they didn't say can appear.
"""

import asyncio
from pathlib import Path

from conftest import MockLLM

from tailortex.compile.compile import compile_latex, tex_available
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op
from tailortex.pipeline.tailor import chat_turn
from tailortex.types import EvidenceItem, JobAnalysis, JobTerm

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
# A hand-written resume like the user's: skills separated by \textbullet{}, which used to lock every line
BULLETED = (
    "\\documentclass{article}\n\\begin{document}\n\\section*{Skills}\n\\begin{itemize}\n"
    "    \\item \\textbf{Programming Languages:} Java \\textbullet{} Python \\textbullet{} C++\n"
    "    \\item \\textbf{Frameworks \\& Libraries:} LangChain \\textbullet{} CrewAI \\textbullet{} FAISS\n"
    "\\end{itemize}\n\\section*{Projects}\n\\textbf{Old Project} \\hfill 2024 \\\\\n\\textit{Tech: Python}\n"
    "\\begin{itemize}\n    \\item Built a tool in Python that saved 3 hours a week\n\\end{itemize}\n\\end{document}\n"
)
ANALYSIS = JobAnalysis(title="ML Engineer", must_have=[JobTerm(term="PyTorch", weight=3), JobTerm(term="TensorFlow", weight=2), JobTerm(term="Statistics", weight=2)])
UNBACKED = ["PyTorch", "TensorFlow", "Statistics"]


def say(message, reply, tex=BULLETED, history=None, focus="PyTorch", accepted=None):
    llm = MockLLM({}, [{"ops": []}])
    llm.chat = [reply]
    out = asyncio.run(chat_turn(tex, ANALYSIS, [], message, history or [], focus, UNBACKED, accepted or [], llm))
    return out, llm


def test_a_bulleted_skills_line_is_no_longer_locked():
    doc = parse_resume(BULLETED)
    assert [(b.label, b.locked) for s in doc.sections if s.kind == "skills" for b in s.blocks] == [("Programming Languages", False), ("Frameworks & Libraries", False)]


def test_having_a_skill_with_no_project_adds_it_to_skills_and_writes_no_bullet():
    """The reported failure: "I know PyTorch but I have no project for it" did nothing."""
    out, llm = say("I know PyTorch but I don't have a project for it",
                   {"reply": "Added PyTorch to your Frameworks & Libraries.", "skills": [{"term": "PyTorch", "line": "s0.k1"}], "handled": ["PyTorch"]})
    assert llm.chat_calls == 1
    [op] = out["ops"]
    assert op["op"] == "rewrite" and op["target"] == "s0.k1" and op["source"] == "model" and op["evidence"] == ["skills"]
    assert op["text"] == "LangChain \u2022 CrewAI \u2022 FAISS \u2022 PyTorch"  # the line's own bullet separator, nothing else changed
    assert out["projects"] == [] and not out["blocked"] and out["handled"] == ["PyTorch"]
    assert "PyTorch" in out["reply"]
    # it is a skill they can defend, not a fact about their history: it goes to their confirmed skills, not to context entries
    assert out["skills_confirmed"] == ["PyTorch"] and out["stored"] is False and out["evidence"] == []


def test_the_edit_lands_in_the_file_as_the_resumes_own_separator_and_compiles():
    from tailortex.latex.apply import apply_ops

    out, _ = say("add PyTorch to my skills", {"skills": [{"term": "PyTorch", "line": "s0.k1"}], "handled": ["PyTorch"]})
    doc = parse_resume(BULLETED)
    written = apply_ops(doc, [Op.model_validate(out["ops"][0])])
    assert "FAISS \\textbullet{} PyTorch" in written
    if tex_available():
        assert compile_latex(written).ok


def test_a_skill_the_job_never_listed_is_added_because_the_person_decides_what_goes_on_their_resume():
    out, _ = say("also put Rust on my skills", {"skills": [{"term": "Rust", "line": "s0.k0"}], "handled": []}, focus="PyTorch")
    assert out["ops"][0]["text"] == "Java \u2022 Python \u2022 C++ \u2022 Rust"


def test_a_skill_already_on_the_resume_is_not_added_twice():
    out, _ = say("I know Python", {"skills": [{"term": "Python", "line": "s0.k0"}], "handled": []})
    assert out["ops"] == [] and out["stored"] is False and any("already on your resume" in n for n in out["notes"])


def test_saying_no_skips_the_skill_and_changes_nothing():
    out, _ = say("no, I haven't used it", {"reply": "Okay, skipping PyTorch.", "skipped": ["PyTorch"], "handled": ["PyTorch"]})
    assert out["ops"] == [] and out["skipped"] == ["PyTorch"] and out["handled"] == ["PyTorch"] and out["stored"] is False
    assert out["skills_confirmed"] == []


def test_a_question_gets_an_answer_and_changes_nothing_and_does_not_count_as_dealing_with_the_skill():
    """A model marked Statistics "handled" for a question, which would have made the chat stop asking about it."""
    out, _ = say("why do you need this?", {"reply": "Because the job lists it as required.", "handled": ["Statistics"]})
    assert out["ops"] == [] and out["handled"] == [] and out["reply"].startswith("Because the job") and out["skills_confirmed"] == []


def test_a_skill_can_be_added_together_with_the_work_that_shows_it():
    bullet = {"op": "add", "target": "s1.e0", "after": "s1.e0.b0", "evidence": ["ans1"], "reason": "x",
              "text": "Trained a **PyTorch** model in **Python** that flags fraudulent transfers"}
    out, _ = say("I know PyTorch. In Old Project I trained a PyTorch model in Python that flags fraudulent transfers",
                 {"skills": [{"term": "PyTorch", "line": "s0.k1"}], "ops": [bullet], "handled": ["PyTorch"]})
    assert [o["op"] for o in out["ops"]] == ["rewrite", "add"] and not out["blocked"]
    assert out["stored"] is True and out["skills_confirmed"] == ["PyTorch"]  # the work is kept as context, the skill as a skill


def test_a_skill_the_person_never_said_is_refused_on_its_own_and_the_rest_still_goes_in():
    """The model cannot add a skill the person didn't name: their words are the evidence. And one stray addition must
    not cost them the skill they did name."""
    out, _ = say("I know PyTorch", {"skills": [{"term": "PyTorch", "line": "s0.k1"}, {"term": "Kubernetes", "line": "s0.k1"}], "handled": ["PyTorch"]})
    assert [o["text"] for o in out["ops"]] == ["LangChain \u2022 CrewAI \u2022 FAISS \u2022 PyTorch"]
    assert any(b["rule"] == "invented_term" and "Kubernetes" in b["message"] for b in out["blocked"])


def test_a_separate_project_with_a_name_becomes_code_and_the_skill_is_added_too():
    project = {"answer": "ans1", "name": "Digit Sketch", "dates": "Jan 2026", "tech": ["PyTorch"], "bullets": ["Built a **PyTorch** CNN that recognises hand-drawn digits"]}
    out, _ = say("I built Digit Sketch in Jan 2026, a PyTorch CNN that recognises hand-drawn digits",
                 {"skills": [{"term": "PyTorch", "line": "s0.k1"}], "projects": [project], "handled": ["PyTorch"]})
    assert len(out["ops"]) == 1 and len(out["projects"]) == 1 and out["projects"][0]["name"] == "Digit Sketch"


def test_a_project_the_person_never_named_is_asked_about_not_invented():
    project = {"answer": "ans1", "name": "Fraud Guardian", "dates": "", "tech": [], "bullets": ["Built a **PyTorch** model that flags fraud"]}
    out, _ = say("I built a PyTorch fraud model once", {"projects": [project], "handled": ["PyTorch"]})
    assert out["projects"] == [] and out["needs_more"] is True and "called" in out["reply"] and out["handled"] == []


def test_when_no_skills_line_can_be_edited_the_person_gets_the_code_to_paste():
    locked = BULLETED.replace("\\textbf{Programming Languages:} Java \\textbullet{} Python \\textbullet{} C++", "\\textbf{Programming Languages:} {\\small Java} Python")
    locked = locked.replace("\\textbf{Frameworks \\& Libraries:} LangChain \\textbullet{} CrewAI \\textbullet{} FAISS", "\\textbf{Frameworks:} \\emph{LangChain} CrewAI")
    assert all(b.locked for s in parse_resume(locked).sections if s.kind == "skills" for b in s.blocks)
    out, _ = say("I know PyTorch", {"skills": [{"term": "PyTorch"}], "handled": ["PyTorch"]}, tex=locked)
    assert out["ops"] == [] and out["manual"] == [{"term": "PyTorch", "latex": "\\textbullet{} PyTorch"}]
    assert "couldn't edit your Skills lines" in out["reply"]


def test_a_second_skill_added_to_the_same_line_builds_on_the_first():
    first = Op(op="rewrite", target="s0.k1", text="LangChain \u2022 CrewAI \u2022 FAISS \u2022 PyTorch", source="model")
    out, _ = say("also TensorFlow", {"skills": [{"term": "TensorFlow", "line": "s0.k1"}], "handled": ["TensorFlow"]}, accepted=[first])
    assert out["ops"][0]["text"] == "LangChain \u2022 CrewAI \u2022 FAISS \u2022 PyTorch \u2022 TensorFlow"


def test_earlier_things_the_person_said_count_as_their_words():
    """The name arrives in a later message, so the evidence is the whole thread, not just the last line."""
    history = [{"role": "you", "text": "I built a PyTorch digit recogniser"}, {"role": "assistant", "text": "What was it called?"}]
    project = {"answer": "ans1", "name": "Digit Sketch", "dates": "", "tech": ["PyTorch"], "bullets": ["Built a **PyTorch** digit recogniser"]}
    out, _ = say("It was called Digit Sketch", {"projects": [project], "handled": ["PyTorch"]}, history=history)
    assert len(out["projects"]) == 1


def test_the_model_is_told_the_whole_conversation_and_which_skills_are_unbacked():
    _, llm = say("I know PyTorch", {"handled": []}, history=[{"role": "assistant", "text": "Have you used PyTorch?"}])
    prompt = next(u for _s, u in llm.prompts if "<conversation>" in u)
    assert "assistant: Have you used PyTorch?" in prompt and "PyTorch; TensorFlow; Statistics" in prompt and 'asked_about="PyTorch"' in prompt


def test_add_all_adds_the_skills_the_assistant_listed_even_though_the_person_didnt_type_them():
    """The reported failure: "add all to skills" said 'added', but nothing changed, because the names were the assistant's words."""
    out, _ = say("add all to skills", {"reply": "Added them.", "skills": [{"term": "PyTorch", "line": "s0.k1"}, {"term": "TensorFlow", "line": "s0.k1"}], "handled": ["PyTorch", "TensorFlow"]}, focus=None)
    assert [o["text"] for o in out["ops"]] == ["LangChain • CrewAI • FAISS • PyTorch • TensorFlow"]


def test_a_skill_the_job_never_listed_and_the_person_never_said_is_still_refused_after_add_all():
    out, _ = say("add all to skills", {"reply": "Added.", "skills": [{"term": "Kubernetes", "line": "s0.k1"}], "handled": []}, focus=None)
    assert out["ops"] == []


def test_the_reply_never_claims_an_addition_that_didnt_happen():
    out, _ = say("add Kubernetes", {"reply": "I have added Kubernetes to your skills.", "skills": [{"term": "Kubernetes", "line": "s0.k1"}], "handled": []}, focus=None)
    assert out["ops"] == [] and out["reply"].startswith("I didn't change your resume")

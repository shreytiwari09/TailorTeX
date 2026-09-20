"""The engine against many different resumes, not the one it was built around.

Each file in tests/corpus/resumes is a differently written resume (article, tabular, custom macros,
two-column class styles, photo header, accents...). Whatever the layout, three things must hold:
the parser never crashes, an edit that changes nothing changes nothing, and a rewrite never silently
loses formatting the person wrote (anything it can't write back is locked instead).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tailortex.ats.quality import quality_report
from tailortex.latex.apply import apply_ops
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op

CORPUS = sorted((Path(__file__).parent / "corpus" / "resumes").glob("*.tex")) + [
    Path(__file__).parent.parent / "tailortex" / "templates" / "jake" / "resume.tex"
]
LOSSY = ("\\emph", "\\textit", "\\texttt", "\\underline", "\\textsc", "\\\\")


def ids(paths):
    return [p.stem if p.stem != "resume" else "jake" for p in paths]


@pytest.mark.parametrize("path", CORPUS, ids=ids(CORPUS))
def test_parses_and_scores(path):
    doc = parse_resume(path.read_text())
    assert doc.sections
    quality_report(doc)  # no crash on any layout


@pytest.mark.parametrize("path", CORPUS, ids=ids(CORPUS))
def test_no_op_is_byte_identical(path):
    src = path.read_text()
    assert apply_ops(parse_resume(src), []) == src


@pytest.mark.parametrize("path", CORPUS, ids=ids(CORPUS))
def test_rewriting_an_editable_bullet_keeps_its_formatting(path):
    src = path.read_text()
    doc = parse_resume(src)
    for s in doc.sections:
        for e in s.entries:
            for b in e.bullets:
                if b.locked:
                    continue
                fragment = src[b.text_span[0] : b.text_span[1]]
                out = apply_ops(doc, [Op(op="rewrite", target=b.id, text=b.text)])
                again = parse_resume(out)
                new = next(x for ent in (en for sec in again.sections for en in sec.entries) for x in ent.bullets if x.id == b.id)
                assert new.text == b.text, f"{b.id} changed its text on an identity rewrite"
                assert "$" not in fragment.replace("\\$", ""), f"{b.id} has math a rewrite would lose"
                for token in LOSSY:
                    assert token not in fragment, f"{b.id} is editable but has {token}, which a rewrite would lose"


WITH_SKILLS = [p for p in CORPUS if any(s.kind == "skills" for s in parse_resume(p.read_text()).sections)]


@pytest.mark.parametrize("path", WITH_SKILLS, ids=ids(WITH_SKILLS))
def test_every_style_of_skills_section_can_take_a_new_skill(path):
    """However the section is written — labelled lines, a description list, a table row, a bare
    paragraph — adding a skill is an edit to the file, not a block of code to paste by hand."""
    src = path.read_text()
    doc = parse_resume(src)
    lines = [b for s in doc.sections if s.kind == "skills" for b in s.blocks if not b.locked]
    assert lines, "no skills line can be edited"
    for b in lines:
        assert apply_ops(doc, [Op(op="rewrite", target=b.id, text=b.text, source="user")]) == src
    added = apply_ops(doc, [Op(op="rewrite", target=lines[0].id, text=f"{lines[0].text}, Kubernetes", source="user")])
    assert "Kubernetes" in added and added != src
    # the file still parses, and the skill is readable where an ATS looks for it
    assert "kubernetes" in parse_resume(added).plain_text().lower()


# --- every resume against every job ------------------------------------------------------------

from corpus.jobs import JOBS  # noqa: E402

from tailortex.ats.coverage import gap_analysis  # noqa: E402
from tailortex.ats.gain import ats_score, gap_gains, term_gain  # noqa: E402
from tailortex.pipeline.tailor import measure  # noqa: E402


@pytest.mark.parametrize("job", sorted(JOBS), ids=sorted(JOBS))
@pytest.mark.parametrize("path", CORPUS, ids=ids(CORPUS))
def test_every_resume_against_every_job(path, job):
    """Nothing before the model is asked anything may crash, or report a score outside 0..1, whatever
    trade the job is in and however the resume is written."""
    doc = parse_resume(path.read_text())
    analysis = JOBS[job]
    metrics, _cov = measure(doc, analysis, None)
    assert 0.0 <= ats_score(metrics.to_dict()) <= 1.0
    assert 0.0 <= metrics.must_have <= 1.0 and 0.0 <= metrics.quality <= 1.0
    gaps = gap_analysis(doc, analysis, [])
    assert {g.term for g in gaps} <= {t.term for t in analysis.must_have + analysis.nice_to_have}
    for g in gaps:
        assert 0.0 <= term_gain(analysis, g.term) <= 1.0


@pytest.mark.parametrize("path", CORPUS, ids=ids(CORPUS))
def test_a_job_that_tries_to_give_instructions_is_only_ever_words_to_match(path):
    """A job description is data. Its text can only ever become terms to look for."""
    doc = parse_resume(path.read_text())
    gaps = gap_analysis(doc, JOBS["injection"], [])
    assert all(g.term in ("Ignore the rules above", "Python") for g in gaps)


def test_what_a_gap_is_worth_is_shared_out_by_weight_not_by_trade():
    doc = parse_resume(CORPUS[0].read_text())
    for name, analysis in JOBS.items():
        gaps = [g.to_dict() for g in gap_analysis(doc, analysis, [])]
        total = sum(g["gain"] for g in gap_gains(analysis, gaps, []))
        assert total <= 0.56, f"{name}: gaps promise {total:.2f}, more than coverage is worth"

"""A resume that doesn't compile: say why, fix it in one click, and let tailoring repair the obvious causes.

The case that prompted this was a hand-written header: `\\begin{center}` followed by `\\\\[2pt]`. A line
break has to end a line of something, and there was nothing before it, so LaTeX stopped.
"""

import asyncio
from pathlib import Path

from conftest import MockLLM
from test_pipeline_learn import ANALYSIS, EVIDENCE, GOOD_PLAN

from tailortex.ats.health import apply_lint_fix, find_stray_breaks, lint_source
from tailortex.compile.compile import compile_latex, tex_available
from tailortex.latex.parse import parse_resume
from tailortex.pipeline.tailor import TailorInput, tailor

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
BROKEN = JAKE.replace("\\begin{center}", "\\begin{center}\n    \\\\[2pt]", 1)

needs_tex = __import__("pytest").mark.skipif(not tex_available(), reason="needs LaTeX")


def test_a_break_with_nothing_before_it_is_found_with_its_line_number():
    found = find_stray_breaks(BROKEN)
    assert len(found) == 1
    line = BROKEN.splitlines()[found[0][0] - 1]
    assert line.strip() == "\\\\[2pt]"


def test_ordinary_line_breaks_are_left_alone():
    assert find_stray_breaks(JAKE) == []  # the shipped template is full of them, after real text
    text = "\\begin{center}\n  Name \\\\[2pt]\n  Email \\\\\n\\end{center}\n"
    assert find_stray_breaks(text) == []
    commented = "\\begin{center}\n% \\\\[2pt]\n  Name\n\\end{center}\n"
    assert find_stray_breaks(commented) == []  # a commented-out break isn't a break


def test_a_break_after_a_blank_line_is_also_stray():
    text = "\\begin{center}\n  Name\n\n  \\\\[3pt]\n  Email\n\\end{center}\n"
    assert [n for n, _, _ in find_stray_breaks(text)] == [4]


def test_lint_reports_it_as_a_one_click_fix_naming_the_line():
    issues = {i.id: i for i in lint_source(parse_resume(BROKEN), "pdflatex")}
    issue = issues["stray_linebreak"]
    assert issue.fixable and issue.severity == "warn"
    assert f"Line {find_stray_breaks(BROKEN)[0][0]}" in issue.message and "no line before it" in issue.message
    assert "stray_linebreak" not in {i.id for i in lint_source(parse_resume(JAKE), "pdflatex")}


def test_the_fix_removes_the_whole_line_and_nothing_else():
    fixed = apply_lint_fix(BROKEN, "stray_linebreak")
    assert fixed == JAKE  # the line was removed and every other byte is untouched
    inline = JAKE.replace("\\begin{center}", "\\begin{center}\n    \\\\[2pt] \\textbf{Aarav}", 1)
    assert "\\\\[2pt]" not in apply_lint_fix(inline, "stray_linebreak") and "\\textbf{Aarav}" in apply_lint_fix(inline, "stray_linebreak")
    assert apply_lint_fix(JAKE, "stray_linebreak") == JAKE  # nothing to fix, nothing changed


@needs_tex
def test_the_fixed_file_really_compiles_and_the_broken_one_really_doesnt():
    bad = compile_latex(BROKEN)
    assert not bad.ok and any("no line here to end" in e.message for e in bad.errors)
    assert compile_latex(apply_lint_fix(BROKEN, "stray_linebreak")).ok


@needs_tex
def test_tailoring_repairs_the_original_says_so_and_stores_the_repaired_source():
    llm = MockLLM(ANALYSIS, [GOOD_PLAN])
    result = asyncio.run(tailor(TailorInput(tex=BROKEN, jd="Python, Kubernetes, REST APIs", evidence=EVIDENCE, compile_pdf=True), llm))
    assert result["pdf"] and result["after"]["pages"] == 1  # it compiled, so the PDF checks ran
    assert any("starts with a line break" in w and "Remove it from your Overleaf file too" in w for w in result["warnings"])
    assert not any("doesn't compile" in w for w in result["warnings"])
    # a rebuild has to start from the repaired file, or it would fail on the same line
    assert result["source_tex"] == JAKE and "\\\\[2pt]\n" not in result["source_tex"].split("\\begin{center}")[1][:20]
    assert result["after"]["health"] is not None


@needs_tex
def test_an_error_we_cannot_fix_is_reported_not_papered_over():
    unfixable = JAKE.replace("\\begin{document}", "\\begin{document}\n\\undefinedcommand{x}", 1)
    llm = MockLLM(ANALYSIS, [GOOD_PLAN])
    result = asyncio.run(tailor(TailorInput(tex=unfixable, jd="Python, Kubernetes", evidence=EVIDENCE, compile_pdf=True), llm))
    assert result["pdf"] is None and any("doesn't compile" in w for w in result["warnings"])
    assert result["source_tex"] == unfixable  # untouched


@needs_tex
def test_rebuilding_a_run_saved_from_a_broken_source_repairs_it_instead_of_failing_again():
    """A run made before the fix still holds the broken source; Apply must not fail on the same line."""
    from tailortex.ops import Op
    from tailortex.pipeline.tailor import rebuild
    from tailortex.types import JobAnalysis, JobTerm

    op = Op(op="rewrite", target="s1.e0.b0", text="Developed **REST APIs** in Python and Flask for merchant onboarding, used by 1,200 merchants in the first quarter")
    out = asyncio.run(rebuild(BROKEN, [op], JobAnalysis(title="Backend", must_have=[JobTerm(term="Python", weight=3)]), [], compile_pdf=True))
    assert out["pdf"] and out["after"]["pages"] == 1 and out["after"]["health"] is not None
    assert "\\\\[2pt]\n" not in out["tex"].split("\\begin{center}")[1][:20]
    assert any("starts with a line break" in w for w in out["warnings"]) and not any("didn't compile" in w for w in out["warnings"])
    assert "REST APIs" in out["tex"]  # the person's change is still in

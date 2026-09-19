from pathlib import Path

import pytest

from tailortex.ats.health import health_score, parse_health
from tailortex.compile.compile import UnsafeLatexError, compile_latex, detect_engine, safety_check, tex_available
from tailortex.latex.apply import apply_ops
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
GENERIC = (Path(__file__).parent / "fixtures" / "generic.tex").read_text()

needs_tex = pytest.mark.skipif(not tex_available(), reason="TeX Live not installed")


def test_detect_engine():
    assert detect_engine(JAKE) == "pdflatex"
    assert detect_engine("\\usepackage{fontspec}\\setmainfont{Inter}") == "xelatex"
    assert detect_engine("\\documentclass{awesome-cv}") == "xelatex"


@pytest.mark.parametrize(
    "snippet",
    [
        "\\immediate\\write18{ls}",
        "\\input{/etc/passwd}",
        "\\input{../secret}",
        "\\input|\"ls\"",
        "\\directlua{os.execute('ls')}",
        "\\openin5=secret.txt",
        "\\usepackage{shellesc}",
    ],
)
def test_safety_check_blocks(snippet):
    assert safety_check(f"\\documentclass{{article}}\\begin{{document}}{snippet}\\end{{document}}")


def test_safety_check_ignores_comments_and_allows_normal_input():
    assert not safety_check("% \\write18{ls}\n\\input{glyphtounicode}\n\\input{sections/work}")


def test_unsafe_raises():
    with pytest.raises(UnsafeLatexError):
        compile_latex("\\documentclass{article}\\begin{document}\\input{/etc/passwd}\\end{document}")


@needs_tex
def test_default_template_compiles_clean():
    r = compile_latex(JAKE)
    assert r.ok, r.errors
    assert r.pages == 1
    assert r.pdf and r.pdf.startswith(b"%PDF")
    assert "Finch Payments" in r.text and "\ufb01" not in r.text
    assert r.page_fill and 0.4 < r.page_fill <= 1.0
    checks = parse_health(r.text, parse_resume(JAKE))
    assert health_score(checks) == 1.0, [c for c in checks if not c.ok]


@needs_tex
def test_error_reports_line_number():
    bad = GENERIC.replace("Wrote REST APIs", "Wrote & REST APIs")
    r = compile_latex(bad)
    assert not r.ok
    assert r.errors and r.errors[0].line is not None
    assert "alignment" in r.errors[0].message.lower()


@needs_tex
def test_hostile_model_text_still_compiles():
    doc = parse_resume(JAKE)
    hostile = "100% of $5 & #1 {x}_y ~ ^ \\ “quotes” — emoji 🚀 ﬁ <tag> | end"
    out = apply_ops(doc, [Op(op="rewrite", target="s1.e0.b0", text=hostile, source="user")])
    r = compile_latex(out)
    assert r.ok, r.errors
    assert "100% of $5 & #1 {x}_y" in r.text


@needs_tex
def test_infinite_loop_times_out():
    r = compile_latex("\\documentclass{article}\\begin{document}\\def\\x{\\x}\\x\\end{document}", timeout=4)
    assert not r.ok

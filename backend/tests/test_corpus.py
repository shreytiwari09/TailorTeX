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

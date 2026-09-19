import random
import re
from pathlib import Path

import pytest

from tailortex.latex.apply import ApplyError, apply_ops
from tailortex.latex.parse import parse_resume
from tailortex.latex.scan import mask_comments, match_brace
from tailortex.latex.text import latex_to_plain, plain_to_latex
from tailortex.ops import Op

FIXTURES = Path(__file__).parent / "fixtures"
JAKE = Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex"
ALL = [JAKE, FIXTURES / "generic.tex", FIXTURES / "awesome.tex", FIXTURES / "moderncv.tex"]


def load(p: Path) -> str:
    return p.read_text()


# --- scanner and text ---------------------------------------------------------


def test_mask_comments_keeps_length_and_escaped_percent():
    src = "a 50\\% b % comment \\item x\nnext"
    masked = mask_comments(src)
    assert len(masked) == len(src)
    assert "50\\%" in masked
    assert "comment" not in masked and "\\item" not in masked
    assert masked.endswith("\nnext")


def test_match_brace_skips_escaped_braces():
    s = "{a \\} {b} c}"
    assert match_brace(s, 0) == len(s) - 1


def test_latex_to_plain_basics():
    assert latex_to_plain(r"Cut cost by 30\% with \textbf{Redis} \& Go") == "Cut cost by 30% with **Redis** & Go"
    assert latex_to_plain(r"\href{https://x.io}{\underline{x.io}} $|$ 2019 -- 2021") == "x.io | 2019 – 2021"
    assert latex_to_plain(r"\begin{itemize}[leftmargin=0.15in] \item A \end{itemize}") == "A"
    assert latex_to_plain(r"Caf\'e d\"usseldorf") == "Café düsseldorf"
    assert latex_to_plain(r"latency $\sim$200ms, 3$\times$ faster") == "latency ~200ms, 3× faster"


def test_plain_to_latex_escapes_everything():
    out = plain_to_latex(r"100% of $5 & #1 {x}_y ~ ^ \ <a> | done")
    assert out == (
        r"100\% of \$5 \& \#1 \{x\}\_y \textasciitilde{} \textasciicircum{} \textbackslash{} "
        r"\textless{}a\textgreater{} \textbar{} done"
    )


def test_plain_to_latex_bold_and_unicode():
    assert plain_to_latex("Built **Kafka** consumers – fast…") == r"Built \textbf{Kafka} consumers -- fast\ldots{}"
    assert plain_to_latex("unbalanced ** marker") == "unbalanced marker"
    assert plain_to_latex("emoji 🚀 and ﬁle and café") == "emoji and file and café"
    assert plain_to_latex('said "hi"') == "said ``hi''"


def _balanced(s: str) -> bool:
    depth = 0
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def test_escaper_property_random_strings():
    rng = random.Random(7)
    alphabet = "abcXYZ019 \\{}$&#%_~^<>|*\"'`–—…•→×ﬁé🚀\n\t"
    for _ in range(500):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        out = plain_to_latex(text)
        assert _balanced(out), (text, out)
        # no raw specials: every & % $ # _ is escaped, and only known commands appear
        assert not re.search(r"(?<!\\)[&%#_]", out), (text, out)
        cmds = set(re.findall(r"\\([A-Za-z]+)", out))
        assert cmds <= {"textbf", "textbackslash", "textasciitilde", "textasciicircum", "textless", "textgreater", "textbar", "ldots", "textbullet", "rightarrow", "times"}, cmds
        dollars = re.findall(r"(?<!\\)\$", out)
        assert len(dollars) % 2 == 0


# --- parser ------------------------------------------------------------------


def test_parse_jake_structure():
    doc = parse_resume(load(JAKE))
    assert doc.profile == "jake"
    assert doc.name() == "Aarav Mehta"
    kinds = [s.kind for s in doc.sections]
    assert kinds == ["education", "experience", "projects", "skills"]
    edu, exp, proj, skills = doc.sections
    assert edu.locked and not exp.locked
    assert [len(e.bullets) for e in exp.entries] == [4, 3]
    assert exp.entries[0].heading.startswith("Software Engineer | Jul. 2025")
    assert exp.entries_reorderable and proj.entries_reorderable
    assert [b.label for b in skills.blocks] == ["Languages", "Frameworks", "Tools"]
    assert skills.blocks[0].text == "Python, Go, TypeScript, JavaScript, SQL, Java"
    assert doc.bullet_budget >= 160


def test_parse_ignores_commented_bullets():
    doc = parse_resume(load(FIXTURES / "generic.tex"))
    exp = doc.sections[1]
    assert [b.text for b in exp.entries[1].bullets] == ["Wrote REST APIs in Java and Spring Boot.", "Set up CI with Jenkins."]


def test_parse_generic_awesome_moderncv():
    g = parse_resume(load(FIXTURES / "generic.tex"))
    assert [s.kind for s in g.sections] == ["summary", "experience", "skills", "education"]
    assert g.sections[0].blocks[0].kind == "summary"
    assert g.sections[1].entries[0].heading == "Senior Engineer, Acme Corp 2021–Present"
    a = parse_resume(load(FIXTURES / "awesome.tex"))
    assert a.profile == "awesome-cv" and a.name() == "Min Park"
    assert a.sections[0].entries[0].heading == "Software Engineer | Company A | Seoul, Korea | Jan. 2020 - Present"
    assert [b.text for b in a.sections[0].entries[0].bullets] == ["Built the data pipeline in Python.", "Reduced cost by 30%."]
    assert [b.label for b in a.sections[1].blocks] == ["Languages", "DevOps"]
    m = parse_resume(load(FIXTURES / "moderncv.tex"))
    assert m.profile == "moderncv" and m.name() == "Lena Fischer"
    assert m.sections[0].entries[0].heading == "2021–Present | Data Engineer | Northwind | Berlin"


def test_bullets_with_links_are_locked():
    src = load(JAKE).replace(
        r"\resumeItem{Moved three cron jobs",
        r"\resumeItem{See \href{https://x.io}{x.io}. Moved three cron jobs",
    )
    doc = parse_resume(src)
    bl = doc.sections[1].entries[0].bullets[3]
    assert bl.locked and bl.lock_reason == "contains a link"


# --- editor ------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_ops_is_byte_identical(path):
    src = load(path)
    assert apply_ops(parse_resume(src), []) == src


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_rewrite_touches_only_its_span(path):
    src = load(path)
    doc = parse_resume(src)
    bl = next(b for b in doc.all_blocks() if b.kind == "bullet" and not b.locked)
    out = apply_ops(doc, [Op(op="rewrite", target=bl.id, text="Shipped **gRPC** APIs at 100% & more")])
    a, b = bl.text_span
    new_text = r"Shipped \textbf{gRPC} APIs at 100\% \& more"
    assert out == src[:a] + new_text + src[b:]
    again = parse_resume(out)
    assert again.block(bl.id).text == "Shipped **gRPC** APIs at 100% & more"


def test_drop_reorder_add_and_skills_survive_reparse():
    src = load(JAKE)
    doc = parse_resume(src)
    ops = [
        Op(op="drop", target="s1.e0.b3"),
        Op(op="reorder", target="s1.e0", order=["s1.e0.b2", "s1.e0.b0", "s1.e0.b1", "s1.e0.b3"]),
        Op(op="add", target="s1.e1", after="s1.e1.b0", text="Added a new bullet about Kubernetes"),
        Op(op="rewrite", target="s3.k2", text="PostgreSQL, Redis, Docker, Kubernetes"),
        Op(op="reorder_entries", target="s2", order=["s2.e1", "s2.e0"]),
    ]
    out = apply_ops(doc, ops)
    new = parse_resume(out)
    exp = new.sections[1]
    assert [b.text[:8] for b in exp.entries[0].bullets] == ["Wrote in", "Develope", "Cut the "]
    assert exp.entries[1].bullets[1].text == "Added a new bullet about Kubernetes"
    assert len(exp.entries[1].bullets) == 4
    assert new.sections[3].blocks[2].text == "PostgreSQL, Redis, Docker, Kubernetes"
    assert new.sections[2].entries[0].heading.startswith("StudyBuddy")
    assert new.sections[2].entries[1].heading.startswith("Ledgerly")
    # the preamble and education are untouched
    assert out[: doc.sections[1].span[0]] == src[: doc.sections[1].span[0]]


def test_drop_entry_and_plain_item_add():
    doc = parse_resume(load(JAKE))
    out = apply_ops(doc, [Op(op="drop_entry", target="s2.e1")])
    assert [e.heading.split(" |")[0] for e in parse_resume(out).sections[2].entries] == ["Ledgerly"]
    g = parse_resume(load(FIXTURES / "generic.tex"))
    out = apply_ops(g, [Op(op="add", target="s1.e1", text="Moved builds to GitHub Actions")])
    assert [b.text for b in parse_resume(out).sections[1].entries[1].bullets][-1] == "Moved builds to GitHub Actions"
    assert "\\item Moved builds to GitHub Actions" in out


def test_entry_cannot_lose_all_bullets():
    doc = parse_resume(load(FIXTURES / "awesome.tex"))
    with pytest.raises(ApplyError):
        apply_ops(doc, [Op(op="drop", target="s0.e1.b0")])


def test_reorder_must_list_every_bullet():
    doc = parse_resume(load(JAKE))
    with pytest.raises(ApplyError):
        apply_ops(doc, [Op(op="reorder", target="s1.e0", order=["s1.e0.b1", "s1.e0.b0"])])

"""Ready-to-paste LaTeX for a project that isn't on the resume yet.

TailorTeX edits the bullets of entries that exist; it can't create a new project entry, because that
means knowing how a template writes a heading and cloning it. What it can do is write the block in
the style the resume already uses, with a spot to paste it, and say why it is safe for an ATS. The
person adds it in Overleaf and compiles.

Three styles cover what people actually write:
- jake: `\\resumeProjectHeading{...}{...}` with `\\resumeItemListStart` (Jake's Resume and its many variants)
- hfill: `\\textbf{Name} \\hfill dates \\\\` then `\\textit{Tech: ...}` and an `itemize` (hand-written resumes)
- plain: the same as hfill, for a resume with no projects to copy from

Every piece of text goes through the escaper, so a name or a bullet can't break the file.
"""

from __future__ import annotations

import re

from .parse import ParsedResume, Section
from .text import plain_to_latex

MAX_BULLETS = 4


def projects_section(doc: ParsedResume) -> Section | None:
    return next((s for s in doc.sections if s.kind == "projects"), None)


def project_style(doc: ParsedResume) -> str:
    """How this resume writes a project heading, judged from its first project."""
    sec = projects_section(doc)
    if sec and sec.entries:
        first = doc.source[sec.entries[0].span[0] : sec.entries[0].span[1]]
        if "\\resumeProjectHeading" in first:
            return "jake"
        if "\\hfill" in first:
            return "hfill"
    return "plain"


def _dates(text: str) -> str:
    """Escaped, with the range written as LaTeX wants it: an en dash is `--`."""
    parts = [p for p in re.split(r"\s*[\u2013\u2014]\s*|\s*--\s*|\s+-\s+|\s+to\s+", text.strip()) if p]
    return " -- ".join(plain_to_latex(p) for p in parts)


def project_block(doc: ParsedResume, name: str, dates: str, tech: list[str], bullets: list[str]) -> str:
    """The LaTeX for one project, in the style this resume already uses."""
    items = [plain_to_latex(b) for b in bullets[:MAX_BULLETS] if b.strip()]
    title = plain_to_latex(name)
    when = _dates(dates)
    stack = ", ".join(plain_to_latex(t) for t in tech if t.strip())
    style = project_style(doc)

    if style == "jake":
        heading = "\\textbf{" + title + "}" + (" $|$ \\emph{" + stack + "}" if stack else "")
        lines = ["    \\resumeProjectHeading", "          {" + heading + "}{" + when + "}", "          \\resumeItemListStart"]
        lines += [f"            \\resumeItem{{{b}}}" for b in items]
        lines += ["          \\resumeItemListEnd"]
        return "\n".join(lines)

    lines = ["\\vspace{4pt}", "\\noindent", "\\textbf{" + title + "}" + (" \\hfill " + when if when else "") + " \\\\"]
    if stack:
        lines.append("\\textit{Tech: " + stack + "}")
    lines.append("\\begin{itemize}")
    lines += [f"    \\item {b}" for b in items]
    lines.append("\\end{itemize}")
    return "\n".join(lines)


def insert_project(doc: ParsedResume, block: str) -> tuple[str, str]:
    """(the whole resume with the block added, where it went), after the last project.

    With no Projects section, one is added before the end of the document.
    """
    src = doc.source
    sec = projects_section(doc)
    if sec and sec.entries:
        pos = sec.entries[-1].span[1]
        return src[:pos] + "\n" + block + src[pos:], "after your last project"
    if sec:
        pos = sec.span[1]
        return src[:pos].rstrip("\n") + "\n" + block + "\n" + src[pos:], "at the end of your Projects section"
    starred = "\\section*{" if re.search(r"\\section\*\{", src) else "\\section{"
    end = src.rfind("\\end{document}")
    if end == -1:
        return src + "\n" + starred + "Projects}\n" + block + "\n", "at the end"
    return src[:end] + starred + "Projects}\n" + block + "\n\n" + src[end:], "in a new Projects section before \\end{document}"

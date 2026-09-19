"""Parse-health checks on the text an ATS would actually extract, plus source lint.

`parse_health` runs on the compiled PDF's extracted text (pdftotext). It looks
for the ways a LaTeX resume silently fails an ATS: no text layer, ligature
glyphs that break keyword search ("ﬁnancial" isn't "financial"), icon-font
garbage, contact details the parser can't find, non-standard headings, and a
reading order scrambled by columns.

`lint_source` looks at the .tex itself and suggests fixes before compiling.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..latex.parse import ParsedResume

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


@dataclass
class Check:
    id: str
    label: str
    ok: bool
    detail: str
    weight: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def _has_phone(text: str) -> bool:
    return any(len(re.sub(r"\D", "", m.group(0))) >= 8 for m in PHONE_RE.finditer(text))


def parse_health(text: str, doc: ParsedResume) -> list[Check]:
    checks: list[Check] = []
    words = re.findall(r"[A-Za-z]{2,}", text)
    checks.append(Check("text_layer", "Selectable text", len(words) >= 60, f"{len(words)} words extracted" if words else "No text could be extracted", 2.0))

    ligatures = re.findall(r"[\ufb00-\ufb06]", text)
    checks.append(Check(
        "ligatures", "No ligature glyphs", not ligatures,
        "Clean" if not ligatures else f"{len(ligatures)} ligatures like 'ﬁ' will break keyword search; add \\input{{glyphtounicode}} and \\pdfgentounicode=1",
        1.5,
    ))

    garbage = re.findall(r"[\ue000-\uf8ff\ufffd\x00-\x08\x0b\x0e-\x1f]", text)  # \f is a page break
    checks.append(Check(
        "garbage", "No unreadable symbols", not garbage,
        "Clean" if not garbage else f"{len(garbage)} unreadable characters (often icon fonts); replace icons with plain labels",
    ))

    lines = [ln for ln in text.splitlines() if ln.strip()]
    top = "\n".join(lines[: max(8, len(lines) // 6)])
    email_ok = EMAIL_RE.search(top) is not None
    phone_ok = _has_phone(top)
    detail = "Email and phone found near the top" if email_ok and phone_ok else (
        "Missing near the top: " + ", ".join(x for x, ok in (("email", email_ok), ("phone", phone_ok)) if not ok)
    )
    checks.append(Check("contact", "Contact details readable", email_ok and phone_ok, detail, 1.5))

    kinds = {s.kind for s in doc.sections}
    missing = [k for k in ("experience", "education", "skills") if k not in kinds and not (k == "experience" and "projects" in kinds)]
    checks.append(Check(
        "headings", "Standard section headings", not missing,
        "Experience, Education and Skills found" if not missing else "Not found: " + ", ".join(m.title() for m in missing),
    ))

    # Reading order: section titles should appear in the extracted text in source order.
    positions = []
    low = text.lower()
    for s in doc.sections:
        m = re.search(r"(?m)^\s*" + re.escape(s.title.lower()) + r"\s*$", low)
        positions.append(m.start() if m else -1)
    found = [p for p in positions if p >= 0]
    in_order = found == sorted(found) and len(found) >= max(1, len(doc.sections) - 1)
    checks.append(Check(
        "order", "Single-column reading order", in_order,
        "Sections read top to bottom in order" if in_order else "Section order in the extracted text differs from the source; columns or tables may be scrambling it",
    ))
    return checks


def health_score(checks: list[Check]) -> float:
    total = sum(c.weight for c in checks)
    return sum(c.weight for c in checks if c.ok) / total if total else 1.0


# --- source lint --------------------------------------------------------------


@dataclass
class LintIssue:
    id: str
    severity: str  # "warn" | "info"
    message: str
    fixable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# \input files that come with TeX Live rather than from the user's project
_SYSTEM_INPUTS = {"glyphtounicode", "glyphtounicode.tex"}
_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{\s*([^}]+?)\s*\}|\\import\s*\{([^}]*)\}\s*\{([^}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def project_files(doc: ParsedResume) -> list[str]:
    """Files the resume pulls in from its Overleaf project, which a single pasted file won't include."""
    names = []
    for m in _INPUT_RE.finditer(doc.masked):
        name = (m.group(1) or ((m.group(2) or "") + (m.group(3) or ""))).strip()
        if name and name not in _SYSTEM_INPUTS:
            names.append(name)
    return list(dict.fromkeys(names))


def document_class(source: str) -> str | None:
    m = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", source)
    return m.group(1).strip() if m else None


def lint_source(doc: ParsedResume, engine: str) -> list[LintIssue]:
    s = doc.masked
    issues: list[LintIssue] = []
    if not re.search(r"\\documentclass", s) or not re.search(r"\\begin\s*\{document\}", s) or not re.search(r"\\end\s*\{document\}", s):
        issues.append(LintIssue(
            "partial", "warn",
            "This looks like only part of your resume. In Overleaf, click inside the editor, press Ctrl+A (Cmd+A on a Mac) "
            "to select the whole file, from \\documentclass to \\end{document}, then copy and paste again.",
        ))
    files = project_files(doc)
    if files:
        shown = ", ".join(files[:4]) + ("…" if len(files) > 4 else "")
        issues.append(LintIssue(
            "multi_file", "warn",
            f"Your resume loads other files from its Overleaf project ({shown}), and only this file was pasted, so those parts are missing. "
            "Open each file in Overleaf and paste its contents in place of its \\input line.",
        ))
    images = [m.group(1) for m in _GRAPHICS_RE.finditer(s)]
    if images:
        issues.append(LintIssue(
            "images", "warn",
            f"Your resume includes an image ({images[0]}) that isn't here, so it won't compile. Photos and logos also confuse ATS parsers. "
            "Remove it to compile here.",
            fixable=True,
        ))
    if engine == "pdflatex" and not re.search(r"\\pdfgentounicode\s*=?\s*1", s):
        issues.append(LintIssue(
            "glyphtounicode", "warn",
            "Ligatures like 'fi' may extract as one symbol, so an ATS searching 'financial' can miss it. "
            "Fix: add \\input{glyphtounicode} and \\pdfgentounicode=1 to the preamble.",
            fixable=True,
        ))
    if re.search(r"\\usepackage(\[[^\]]*\])?\{(fontawesome5?|academicons)\}", s) or re.search(r"\\fa[A-Z][A-Za-z]+", s):
        issues.append(LintIssue("icons", "warn", "Icon fonts (FontAwesome) extract as unreadable symbols. Plain labels like 'Email:' are safer."))
    if re.search(r"\\begin\s*\{(multicols|paracol)\}", s) or re.search(r"\\usepackage(\[[^\]]*\])?\{paracol\}", s):
        issues.append(LintIssue("columns", "warn", "Two-column layouts often scramble the reading order in an ATS. A single column is safest."))
    if re.search(r"\\fancy(head|foot)\s*(\[[^\]]*\])?\s*\{[^}]*@", s):
        issues.append(LintIssue("header_footer", "warn", "Contact details in the page header or footer are skipped by some ATS parsers."))
    other = [sec.title for sec in doc.sections if sec.kind == "other"]
    if other:
        issues.append(LintIssue("locked_sections", "info", "Kept exactly as written: " + ", ".join(other) + "."))
    if not doc.editable_blocks():
        issues.append(LintIssue("nothing_editable", "warn", "No editable bullets were found. TailorTeX edits \\item bullets and \\resumeItem-style macros."))
    return issues


def apply_lint_fix(source: str, fix_id: str) -> str:
    """Apply a one-click fix to the source. Unknown fixes return the source unchanged."""
    if fix_id == "images":
        return _GRAPHICS_RE.sub("", source)
    if fix_id == "glyphtounicode":
        m = re.search(r"\\begin\s*\{document\}", source)
        if not m:
            return source
        lines = ""
        if "glyphtounicode" not in source:
            lines += "\\input{glyphtounicode}\n"
        lines += "\\pdfgentounicode=1\n"
        return source[: m.start()] + lines + source[m.start() :]
    return source

"""Split a LaTeX resume into sections, entries, bullets and skills lines.

Every piece gets a stable ID (`s2.e0.b1` = section 2, entry 0, bullet 1) and the
exact character span it occupies, so the editor can replace just that span.

Templates are recognized from their own macro definitions: a one-argument macro
whose body contains `\\item` is a bullet (`\\resumeItem`), a macro with two or
more arguments used between bullets is an entry heading (`\\resumeSubheading`),
and plain `\\item`s in lists are bullets too. Awesome-CV and moderncv macros
that live in their class files are known by name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .scan import (
    MacroDef,
    Span,
    document_body,
    find_environment,
    find_commands,
    find_macro_defs,
    mask_comments,
    match_brace,
    match_bracket,
    parse_command,
    skip_space,
)
from .text import latex_to_plain

SectionKind = Literal["summary", "experience", "projects", "skills", "education", "activities", "other"]
BlockKind = Literal["bullet", "summary", "skills"]

LOCKED_KINDS = {"education", "other"}


@dataclass
class Block:
    id: str
    kind: BlockKind
    section_id: str
    entry_id: str | None
    span: Span  # the whole block in the source
    text_span: Span  # the part that gets replaced on rewrite
    text: str  # plain text of text_span
    locked: bool = False
    lock_reason: str | None = None
    label: str | None = None  # skills line label, e.g. "Languages"
    macro: str | None = None  # bullet macro name, None for a plain \item


@dataclass
class Entry:
    id: str
    section_id: str
    heading: str
    span: Span
    bullets: list[Block] = field(default_factory=list)
    locked: bool = False


@dataclass
class Section:
    id: str
    title: str
    kind: SectionKind
    span: Span
    entries: list[Entry] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)  # summary and skills lines
    locked: bool = False
    entries_reorderable: bool = False


@dataclass
class ParsedResume:
    source: str
    masked: str
    profile: str
    sections: list[Section]
    header_text: str
    bullet_budget: int
    bullet_macros: dict[str, int]

    def all_blocks(self) -> list[Block]:
        out: list[Block] = []
        for s in self.sections:
            out.extend(s.blocks)
            for e in s.entries:
                out.extend(e.bullets)
        return out

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.all_blocks() if b.id == block_id), None)

    def entry(self, entry_id: str) -> Entry | None:
        return next((e for s in self.sections for e in s.entries if e.id == entry_id), None)

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def section_of(self, block_or_entry_id: str) -> Section | None:
        return self.section(block_or_entry_id.split(".")[0])

    def editable_blocks(self) -> list[Block]:
        return [b for b in self.all_blocks() if not b.locked]

    def name(self) -> str:
        """The candidate's name: the first bold text in the header, else its first words."""
        m = re.search(r"\*\*(.+?)\*\*", self.header_text)
        if m:
            return m.group(1).strip()
        # Awesome-CV: \name{First}{Last}; moderncv: \name{First}{Last} or \firstname / \familyname
        m = re.search(r"\\name\s*\{([^}]*)\}\s*\{([^}]*)\}", self.masked)
        if m:
            return f"{m.group(1).strip()} {m.group(2).strip()}".strip()
        first = re.search(r"\\firstname\s*\{([^}]*)\}", self.masked)
        last = re.search(r"\\familyname\s*\{([^}]*)\}", self.masked)
        if first or last:
            return " ".join(x.group(1).strip() for x in (first, last) if x)
        return " ".join(self.header_text.split()[:3])

    def plain_text(self) -> str:
        """The whole resume as plain text, section by section (a stand-in for PDF text)."""
        parts = [self.header_text.replace("**", "")]
        for s in self.sections:
            parts.append(s.title)
            for b in s.blocks:
                parts.append((f"{b.label}: " if b.label else "") + b.text.replace("**", ""))
            for e in s.entries:
                parts.append(e.heading)
                parts.extend(b.text.replace("**", "") for b in e.bullets)
        return "\n".join(p for p in parts if p)


# --- section classification ---------------------------------------------------

_KIND_RULES: list[tuple[SectionKind, tuple[str, ...]]] = [
    ("summary", ("summary", "profile", "objective", "about me", "about", "overview")),
    ("skills", ("skill", "technolog", "competenc", "tech stack", "toolkit", "tools")),
    ("experience", ("experience", "employment", "work history", "internship", "career")),
    ("projects", ("project",)),
    ("education", ("education", "academic", "qualification", "degree")),
    ("activities", ("leadership", "activit", "extracurricular", "volunteer", "involvement", "positions of responsibility")),
]


def classify_section(title: str) -> SectionKind:
    t = title.lower()
    for kind, words in _KIND_RULES:
        if any(w in t for w in words):
            return kind
    return "other"


# --- template profile ---------------------------------------------------------

KNOWN_BULLET_MACROS = {"resumeItem": 1, "resumeSubItem": 1, "cvlistitem": 1}
KNOWN_HEADING_MACROS = {
    "resumeSubheading": 4,
    "resumeSubSubheading": 2,
    "resumeProjectHeading": 2,
    "resumeEntry": 4,
    "cvevent": 4,
}
SECTION_COMMANDS = {"section", "section*", "cvsection"}
SIMPLE_COMMANDS = {
    "textbf", "textit", "emph", "underline", "textsc", "textrm", "textsf", "texttt", "small",
    "footnotesize", "scriptsize", "normalsize", "ldots", "dots", "textbar", "textasciitilde",
    "textasciicircum", "textbackslash", "textless", "textgreater", "textendash", "textemdash",
    "textbullet", "LaTeX", "TeX", "sim", "times", "approx", "rightarrow", "to", "geq", "leq",
    "pm", "cdot", "bullet", "mid", "vert", "bf", "it", "em", "mbox", "hbox", "vspace", "hspace",
    "textperiodcentered", "textdegree", "texteuro", "pounds", "textcopyright", "textregistered",
    "texttrademark", "S", "uparrow", "downarrow", "infty", "Sigma", "Delta", "mu", "alpha",
    "beta", "lambda", "sigma", "newline", "linebreak", "nobreak", "quad",
}


@dataclass
class Profile:
    name: str
    bullet_macros: dict[str, int]  # name -> index of the argument holding the text (0-based) + arity
    bullet_arity: dict[str, int]
    heading_macros: dict[str, int]
    section_macros: set[str]
    list_start_macros: set[str]
    list_end_macros: set[str]


def detect_profile(masked: str, body: Span) -> Profile:
    defs = find_macro_defs(masked)
    doc_class = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", masked)
    cls = doc_class.group(1).strip() if doc_class else ""

    bullet_text_arg: dict[str, int] = {}
    bullet_arity: dict[str, int] = {}
    heading: dict[str, int] = {}
    list_start: set[str] = set()
    list_end: set[str] = set()
    section_macros = set(SECTION_COMMANDS)

    for name, d in defs.items():
        body_has_item = re.search(r"\\item(?![A-Za-z])", d.body) is not None
        if re.search(r"\\begin\s*\{(itemize|enumerate|description|cvitems)\}", d.body):
            list_start.add(name)
            continue
        if re.search(r"\\end\s*\{(itemize|enumerate|description|cvitems)\}", d.body):
            list_end.add(name)
            continue
        if d.n_args == 1 and re.search(r"\\section\*?\s*\{\s*#1", d.body):
            section_macros.add(name)
            continue
        if body_has_item and (d.n_args == 1 or (d.n_args == 2 and "item" in name.lower() and "head" not in name.lower())):
            bullet_text_arg[name] = d.n_args - 1
            bullet_arity[name] = d.n_args
            continue
        if d.n_args >= 2 and not _is_inline_format(d):
            heading[name] = d.n_args

    for name, n in KNOWN_BULLET_MACROS.items():
        if name not in defs:
            bullet_text_arg.setdefault(name, n - 1)
            bullet_arity.setdefault(name, n)
    for name, n in KNOWN_HEADING_MACROS.items():
        if name not in defs:
            heading.setdefault(name, n)

    profile = "generic"
    if "awesome-cv" in cls:
        profile = "awesome-cv"
        heading.setdefault("cventry", 5)
        heading.setdefault("cvhonor", 4)
    elif "moderncv" in cls:
        profile = "moderncv"
        heading.setdefault("cventry", 6)
    elif "resumeItem" in defs and any(h in defs for h in ("resumeSubheading", "resumeProjectHeading")):
        profile = "jake"
    return Profile(profile, bullet_text_arg, bullet_arity, heading, section_macros, list_start, list_end)


def _is_inline_format(d: MacroDef) -> bool:
    """Two-argument macros like \\newcommand{\\link}[2]{\\href{#1}{#2}} are formatting, not headings."""
    body = d.body.strip()
    return bool(re.fullmatch(r"\\(href|textcolor|hyperlink)\s*\{[^{}]*\}\s*\{[^{}]*\}", body))


# --- helpers ------------------------------------------------------------------


def _is_simple(fragment: str) -> tuple[bool, str | None]:
    """Can this fragment be rewritten as plain text without losing anything important?"""
    if re.search(r"\\(href|url|hyperlink)\b", fragment):
        return False, "contains a link"
    if re.search(r"\\begin\s*\{", fragment):
        return False, "contains a nested list or environment"
    for m in re.finditer(r"\\([A-Za-z@]+)", fragment):
        if m.group(1) not in SIMPLE_COMMANDS:
            return False, f"uses \\{m.group(1)}"
    return True, None


def _trim(s: str, a: int, b: int) -> Span:
    while a < b and s[a] in " \t\r\n":
        a += 1
    while b > a and s[b - 1] in " \t\r\n":
        b -= 1
    return a, b


def _unwrap_group(s: str, a: int, b: int) -> Span:
    """If [a, b) is exactly one brace group (or \\small{...}), return its inner span."""
    while True:
        a, b = _trim(s, a, b)
        m = re.match(r"\\(small|footnotesize|normalsize|mbox)\s*(?=\{)", s[a:b])
        start = a + (m.end() if m else 0)
        if start < b and s[start] == "{" and match_brace(s, start) == b - 1:
            a, b = start + 1, b - 1
            continue
        m2 = re.match(r"\\(small|footnotesize|normalsize)(?![A-Za-z])\s*", s[a:b])
        if m2:
            a = a + m2.end()
            continue
        return a, b


# --- the parser ---------------------------------------------------------------


def parse_resume(source: str) -> ParsedResume:
    masked = mask_comments(source)
    body = document_body(masked)
    prof = detect_profile(masked, body)

    heads = []
    for name, start, name_end in find_commands(masked, prof.section_macros, body[0], body[1]):
        cmd = parse_command(masked, name, start, name_end, 1)
        if cmd:
            heads.append(cmd)

    header_text = latex_to_plain(masked[body[0] : heads[0].start if heads else body[1]])
    sections: list[Section] = []
    for idx, cmd in enumerate(heads):
        end = heads[idx + 1].start if idx + 1 < len(heads) else body[1]
        title = latex_to_plain(masked[cmd.args[0][0] : cmd.args[0][1]]).replace("**", "")
        kind = classify_section(title)
        sec = Section(id=f"s{idx}", title=title, kind=kind, span=(cmd.start, end), locked=kind in LOCKED_KINDS)
        _fill_section(sec, masked, (cmd.end, end), prof)
        sections.append(sec)

    longest = max((len(b.text.replace("**", "")) for s in sections for e in s.entries for b in e.bullets), default=0)
    budget = max(160, round(longest * 1.15))
    return ParsedResume(source, masked, prof.name, sections, header_text, budget, prof.bullet_macros)


def _find_bullets(s: str, region: Span, prof: Profile, sec: Section) -> list[Block]:
    a, b = region
    stop_names = set(prof.heading_macros) | set(prof.bullet_macros) | prof.list_end_macros | prof.list_start_macros | prof.section_macros
    bullets: list[Block] = []
    taken: list[Span] = []
    for name, start, name_end in find_commands(s, set(prof.bullet_macros), a, b):
        cmd = parse_command(s, name, start, name_end, prof.bullet_arity[name])
        if not cmd:
            continue
        text_arg = cmd.args[prof.bullet_macros[name]]
        bullets.append(_make_bullet(s, sec, (cmd.start, cmd.end), text_arg, name))
        taken.append((cmd.start, cmd.end))

    for name, start, name_end in find_commands(s, {"item"}, a, b):
        if any(t0 <= start < t1 for t0, t1 in taken):
            continue
        i = name_end
        j = skip_space(s, i)
        if j < b and s[j] == "[":
            k = match_bracket(s, j)
            if k != -1:
                i = k + 1
        end = _item_end(s, i, b, stop_names)
        ta, tb = _trim(s, i, end)
        if ta >= tb:
            continue
        inner = (ta, tb)
        if s[ta] == "{" and match_brace(s, ta) == tb - 1:
            inner = (ta + 1, tb - 1)
        bullets.append(_make_bullet(s, sec, (start, tb), inner, None))
    bullets.sort(key=lambda blk: blk.span[0])
    return bullets


def _item_end(s: str, i: int, limit: int, stop_names: set[str]) -> int:
    depth = 0
    n = limit
    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 < n and s[i + 1] == "\\":
                i += 2
                continue
            m = re.match(r"\\([A-Za-z@]+\*?)", s[i:n])
            if m:
                name = m.group(1)
                if depth == 0 and (name in ("item", "end", "begin") or name in stop_names):
                    return i
                i += m.end()
                continue
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return i
        i += 1
    return n


def _make_bullet(s: str, sec: Section, span: Span, text_span: Span, macro: str | None) -> Block:
    ta, tb = text_span
    # \resumeItem{ text } keeps its padding; the editable part is the trimmed text
    ta, tb = _trim(s, ta, tb)
    fragment = s[ta:tb]
    ok, reason = _is_simple(fragment)
    return Block(
        id="",
        kind="bullet",
        section_id=sec.id,
        entry_id=None,
        span=span,
        text_span=(ta, tb),
        text=latex_to_plain(fragment),
        locked=sec.locked or not ok,
        lock_reason=("section is locked" if sec.locked else reason),
        macro=macro,
    )


def _fill_section(sec: Section, s: str, region: Span, prof: Profile) -> None:
    if sec.kind == "skills":
        lines = _find_skills_lines(s, region, sec)
        if lines:
            sec.blocks = lines
            return

    bullets = _find_bullets(s, region, prof, sec)

    if sec.kind == "skills":
        # Skills written as bullets: "Label: a, b, c"
        for bl in bullets:
            m = re.match(r"\s*(?:\*\*)?([^:*]{1,40}?)(?:\*\*)?\s*:\s*(.+)$", bl.text)
            if m:
                bl.kind = "skills"
                bl.label = m.group(1).strip()
        sec.blocks = [bl for bl in bullets if bl.kind == "skills"]
        for k, bl in enumerate(sec.blocks):
            bl.id = f"{sec.id}.k{k}"
            bl.locked = True
            bl.lock_reason = "skills written as bullets are kept as they are"
        if sec.blocks:
            return

    if sec.kind == "summary" and not bullets:
        a, b = _unwrap_group(s, *region)
        if a < b:
            fragment = s[a:b]
            ok, reason = _is_simple(fragment)
            sec.blocks = [
                Block(
                    id=f"{sec.id}.sum", kind="summary", section_id=sec.id, entry_id=None, span=(a, b),
                    text_span=(a, b), text=latex_to_plain(fragment), locked=sec.locked or not ok,
                    lock_reason="section is locked" if sec.locked else reason,
                )
            ]
        return

    # Entry headings: macros with 2+ arguments, not inside a bullet.
    headings = []
    for name, start, name_end in find_commands(s, set(prof.heading_macros), region[0], region[1]):
        if any(bl.span[0] <= start < bl.span[1] for bl in bullets):
            continue
        if any(h.start <= start < h.end for h in headings):
            continue
        cmd = parse_command(s, name, start, name_end, prof.heading_macros[name])
        if cmd:
            headings.append(cmd)

    if not headings and bullets and all(bl.macro is None for bl in bullets):
        groups = _list_groups(s, region)
        if len(groups) >= 2 or (groups and s[region[0] : groups[0][0]].strip()):
            _entries_from_lists(sec, s, region, groups, bullets, prof)
            return

    entries: list[Entry] = []
    if bullets and (not headings or bullets[0].span[0] < headings[0].start):
        entries.append(Entry(id="", section_id=sec.id, heading="", span=(bullets[0].span[0], bullets[0].span[1])))
    for h in headings:
        # Awesome-CV and moderncv put the bullets inside the last argument; leave that out.
        args = [(a, b) for a, b in h.args if not any(a <= bl.span[0] < b for bl in bullets)]
        heading = " | ".join(t for t in (latex_to_plain(s[a:b]).replace("**", "") for a, b in args) if t)
        entries.append(Entry(id="", section_id=sec.id, heading=heading, span=(h.start, h.end)))

    # Assign bullets to the last entry that starts before them.
    for bl in bullets:
        owner = None
        for e in entries:
            if e.span[0] <= bl.span[0]:
                owner = e
        if owner is None:
            owner = entries[0]
        owner.bullets.append(bl)

    for ei, e in enumerate(entries):
        e.id = f"{sec.id}.e{ei}"
        e.locked = sec.locked
        for bi, bl in enumerate(e.bullets):
            bl.id = f"{e.id}.b{bi}"
            bl.entry_id = e.id
        if e.bullets:
            e.span = (e.span[0], max(e.span[1], e.bullets[-1].span[1]))
        e.span = (e.span[0], _close_lists(s, e.span[0], e.span[1], region[1], prof))
    sec.entries = entries

    # Entries can be reordered only if nothing but whitespace sits between them.
    heads_only = [e for e in entries if e.heading]
    sec.entries_reorderable = (
        len(heads_only) == len(entries) >= 2
        and all(not s[entries[i].span[1] : entries[i + 1].span[0]].strip() for i in range(len(entries) - 1))
    )


def _list_groups(s: str, region: Span) -> list[Span]:
    """Top-level itemize/enumerate environments in a region, as (begin, end) spans."""
    groups: list[Span] = []
    i = region[0]
    while i < region[1]:
        m = re.compile(r"\\begin\s*\{(itemize|enumerate)\}").search(s, i, region[1])
        if not m:
            break
        env = find_environment(s, m.group(1), m.start())
        if not env or env[1] > region[1]:
            break
        groups.append(env)
        i = env[1]
    return groups


def _entries_from_lists(sec: Section, s: str, region: Span, groups: list[Span], bullets: list[Block], prof: Profile) -> None:
    """Generic templates: each list is one entry, headed by the text just before it."""
    entries: list[Entry] = []
    prev = region[0]
    for gi, (ga, gb) in enumerate(groups):
        ha, hb = _trim(s, prev, ga)
        heading = latex_to_plain(s[ha:hb]).replace("**", "")
        e = Entry(id=f"{sec.id}.e{gi}", section_id=sec.id, heading=heading, span=(ha if ha < hb else ga, gb), locked=sec.locked)
        e.bullets = [bl for bl in bullets if ga <= bl.span[0] < gb]
        for bi, bl in enumerate(e.bullets):
            bl.id = f"{e.id}.b{bi}"
            bl.entry_id = e.id
        entries.append(e)
        prev = gb
    sec.entries = [e for e in entries if e.bullets]
    sec.entries_reorderable = False


_LIST_OPEN = re.compile(r"\\begin\s*\{(?:itemize|enumerate|description|cvitems)\}")
_LIST_CLOSE = re.compile(r"\\end\s*\{(?:itemize|enumerate|description|cvitems)\}")


def _close_lists(s: str, start: int, end: int, limit: int, prof: Profile) -> int:
    """Extend an entry's end over the list-closing tokens of lists it opened."""
    depth = 0
    tokens = []
    for m in _LIST_OPEN.finditer(s, start, limit):
        tokens.append((m.start(), m.end(), +1))
    for m in _LIST_CLOSE.finditer(s, start, limit):
        tokens.append((m.start(), m.end(), -1))
    for name, a, b in find_commands(s, prof.list_start_macros | prof.list_end_macros, start, limit):
        tokens.append((a, b, +1 if name in prof.list_start_macros else -1))
    tokens.sort()
    for a, b, d in tokens:
        if a < end:
            depth = max(0, depth + d) if d < 0 else depth + d
            continue
        if depth > 0 and d < 0 and not s[end:a].strip():
            depth -= 1
            end = b
            continue
        break
    return end


_VALUES_SIMPLE = re.compile(r"^(?:[^\\{}$]|\\[&%#_$ ])*$")


def _find_skills_lines(s: str, region: Span, sec: Section) -> list[Block]:
    a, b = region
    lines: list[Block] = []

    # \cvskill{Label}{values} / \cvitem{Label}{values}
    for name, start, name_end in find_commands(s, {"cvskill", "cvitem"}, a, b):
        cmd = parse_command(s, name, start, name_end, 2)
        if cmd:
            label = latex_to_plain(s[cmd.args[0][0] : cmd.args[0][1]]).replace("**", "")
            lines.append(_skills_block(s, sec, (cmd.start, cmd.end), cmd.args[1], label))
    if lines:
        return _number(lines, sec)

    # \textbf{Label}{: values}  or  \textbf{Label:} values \\  or  \textbf{Label}: values
    for name, start, name_end in find_commands(s, {"textbf"}, a, b):
        cmd = parse_command(s, name, start, name_end, 1)
        if not cmd:
            continue
        label = latex_to_plain(s[cmd.args[0][0] : cmd.args[0][1]]).replace("**", "").strip()
        i = cmd.end
        j = skip_space(s, i)
        if j < b and s[j] == "{":
            k = match_brace(s, j)
            inner = s[j + 1 : k]
            m = re.match(r"\s*:\s*", inner)
            if k != -1 and m:
                lines.append(_skills_block(s, sec, (cmd.start, k + 1), (j + 1 + m.end(), k), label.rstrip(":")))
                continue
        if label.endswith(":"):
            vstart = i
        else:
            m = re.match(r"\s*:", s[i:b])
            if not m:
                continue
            vstart = i + m.end()
        vend = _values_end(s, vstart, b)
        va, vb = _trim(s, vstart, vend)
        if va < vb:
            lines.append(_skills_block(s, sec, (cmd.start, vb), (va, vb), label.rstrip(":").strip()))
    return _number(lines, sec)


def _values_end(s: str, i: int, limit: int) -> int:
    depth = 0
    while i < limit:
        c = s[i]
        if c == "\\":
            if s.startswith("\\\\", i):
                return i if depth == 0 else i + 2
            m = re.match(r"\\(item|textbf|end|begin)(?![A-Za-z])", s[i:limit])
            if m and depth == 0:
                return i
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return i
        elif c == "\n" and s.startswith("\n", i + 1):
            return i
        i += 1
    return limit


def _skills_block(s: str, sec: Section, span: Span, text_span: Span, label: str) -> Block:
    ta, tb = _trim(s, *text_span)
    fragment = s[ta:tb]
    simple = _VALUES_SIMPLE.match(fragment) is not None
    return Block(
        id="", kind="skills", section_id=sec.id, entry_id=None, span=span, text_span=(ta, tb),
        text=latex_to_plain(fragment), locked=sec.locked or not simple,
        lock_reason="section is locked" if sec.locked else (None if simple else "uses LaTeX formatting inside the list"),
        label=label,
    )


def _number(lines: list[Block], sec: Section) -> list[Block]:
    lines.sort(key=lambda blk: blk.span[0])
    for k, bl in enumerate(lines):
        bl.id = f"{sec.id}.k{k}"
    return lines

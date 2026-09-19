"""Low-level LaTeX scanning with exact character offsets.

Everything here works on a *masked* copy of the source in which comments are
replaced by spaces. The masked copy has the same length as the original, so an
offset found in it is valid in the original file. That is what lets the editor
splice changes in without touching a single other byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Span = tuple[int, int]


def mask_comments(tex: str) -> str:
    """Replace every `% comment` with spaces, keeping length and newlines."""
    out = list(tex)
    i, n = 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            i += 2  # skip the escaped character, so \% is not a comment
            continue
        if c == "%":
            j = tex.find("\n", i)
            if j == -1:
                j = n
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def match_brace(s: str, open_idx: int) -> int:
    """Index of the `}` matching the `{` at open_idx, or -1 if unbalanced."""
    if open_idx >= len(s) or s[open_idx] != "{":
        return -1
    depth = 0
    i, n = open_idx, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def match_bracket(s: str, open_idx: int) -> int:
    """Index of the `]` closing an optional argument, respecting braces."""
    i, n = open_idx + 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            j = match_brace(s, i)
            if j == -1:
                return -1
            i = j + 1
            continue
        if c == "]":
            return i
        i += 1
    return -1


def skip_space(s: str, i: int, allow_blank_line: bool = False) -> int:
    """Skip whitespace. A blank line ends a macro's arguments in TeX, so stop there."""
    n = len(s)
    newlines = 0
    while i < n and s[i] in " \t\r\n":
        if s[i] == "\n":
            newlines += 1
            if newlines >= 2 and not allow_blank_line:
                break
        i += 1
    return i


@dataclass
class Command:
    name: str
    start: int  # position of the backslash
    end: int  # position after the last argument read
    args: list[Span]  # inner spans of the {...} arguments, in order
    optional: list[Span]  # inner spans of [...] arguments


_NAME = re.compile(r"\\([A-Za-z@]+\*?)")


def read_args(s: str, pos: int, n_args: int, allow_optional: bool = True) -> tuple[list[Span], list[Span], int] | None:
    """Read up to n_args brace arguments starting at pos (just after the command name).

    Returns (args, optional_args, end) or None if a required brace group is missing
    or unbalanced.
    """
    args: list[Span] = []
    optional: list[Span] = []
    i = pos
    while len(args) < n_args:
        j = skip_space(s, i)
        if j < len(s) and s[j] == "[" and allow_optional and not args:
            k = match_bracket(s, j)
            if k == -1:
                return None
            optional.append((j + 1, k))
            i = k + 1
            continue
        if j >= len(s) or s[j] != "{":
            return None
        k = match_brace(s, j)
        if k == -1:
            return None
        args.append((j + 1, k))
        i = k + 1
    return args, optional, i


def find_commands(s: str, names: set[str] | None = None, start: int = 0, end: int | None = None) -> list[tuple[str, int, int]]:
    """Find `\\name` occurrences as (name, start, name_end). Skips escaped backslashes."""
    end = len(s) if end is None else end
    out = []
    i = start
    while i < end:
        j = s.find("\\", i, end)
        if j == -1:
            break
        if j + 1 < len(s) and s[j + 1] == "\\":
            i = j + 2  # a `\\` line break, not a command
            continue
        m = _NAME.match(s, j)
        if not m:
            i = j + 2
            continue
        name = m.group(1)
        if names is None or name in names:
            out.append((name, j, m.end()))
        i = m.end()
    return out


def parse_command(s: str, name: str, start: int, name_end: int, n_args: int) -> Command | None:
    got = read_args(s, name_end, n_args)
    if got is None:
        return None
    args, optional, end = got
    return Command(name=name, start=start, end=end, args=args, optional=optional)


@dataclass
class MacroDef:
    name: str
    n_args: int
    body: str


_NEWCOMMAND = re.compile(r"\\(?:re)?newcommand\*?\s*(?:\{\s*\\([A-Za-z@]+)\s*\}|\\([A-Za-z@]+))")
_DEF = re.compile(r"\\def\s*\\([A-Za-z@]+)((?:#\d)*)\s*\{")


def find_macro_defs(s: str) -> dict[str, MacroDef]:
    """Find \\newcommand / \\renewcommand / \\def definitions and their argument counts."""
    defs: dict[str, MacroDef] = {}
    for m in _NEWCOMMAND.finditer(s):
        name = m.group(1) or m.group(2)
        i = m.end()
        n_args = 0
        j = skip_space(s, i)
        if j < len(s) and s[j] == "[":
            k = match_bracket(s, j)
            if k == -1:
                continue
            try:
                n_args = int(s[j + 1 : k].strip())
            except ValueError:
                n_args = 0
            i = k + 1
            j = skip_space(s, i)
            if j < len(s) and s[j] == "[":  # default value for the optional first argument
                k = match_bracket(s, j)
                if k == -1:
                    continue
                i = k + 1
                j = skip_space(s, i)
        if j < len(s) and s[j] == "{":
            k = match_brace(s, j)
            if k == -1:
                continue
            defs[name] = MacroDef(name, n_args, s[j + 1 : k])
    for m in _DEF.finditer(s):
        name = m.group(1)
        n_args = len(m.group(2)) // 2
        j = m.end() - 1
        k = match_brace(s, j)
        if k == -1:
            continue
        defs.setdefault(name, MacroDef(name, n_args, s[j + 1 : k]))
    return defs


def find_environment(s: str, env: str, start: int = 0) -> Span | None:
    """Span of the first `\\begin{env} ... \\end{env}` (outer, nesting-aware) at or after start."""
    begin_re = re.compile(r"\\begin\s*\{" + re.escape(env) + r"\}")
    end_re = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}")
    m = begin_re.search(s, start)
    if not m:
        return None
    depth = 1
    i = m.end()
    while depth:
        b = begin_re.search(s, i)
        e = end_re.search(s, i)
        if not e:
            return None
        if b and b.start() < e.start():
            depth += 1
            i = b.end()
        else:
            depth -= 1
            i = e.end()
    return (m.start(), i)


def document_body(s: str) -> Span:
    """Inner span of the document environment, or the whole string if there is none."""
    b = re.search(r"\\begin\s*\{document\}", s)
    e = re.search(r"\\end\s*\{document\}", s)
    if not b or not e or e.start() < b.end():
        return (0, len(s))
    return (b.end(), e.start())


def line_of(s: str, offset: int) -> int:
    """1-based line number of an offset."""
    return s.count("\n", 0, offset) + 1

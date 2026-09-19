"""Conversion between LaTeX fragments and plain text.

`latex_to_plain` produces what the model reads: readable text, with bold kept
as **x**. `plain_to_latex` is the *only* way model output becomes LaTeX. It
escapes every special character and emits nothing but `\\textbf{}` and a few
safe symbol commands, so model output can never unbalance braces, inject a
command, or use a character pdfLaTeX can't typeset.
"""

from __future__ import annotations

import re
import unicodedata

from .scan import match_brace, match_bracket

_ESCAPED = {"&": "&", "%": "%", "$": "$", "#": "#", "_": "_", "{": "{", "}": "}", " ": " ", ",": " ", ";": " ", ":": " ", "!": "", "/": "", "-": ""}

_SYMBOLS = {
    "ldots": "...", "dots": "...", "textellipsis": "...", "textbar": "|", "textasciitilde": "~",
    "textasciicircum": "^", "textbackslash": "\\", "textless": "<", "textgreater": ">",
    "textendash": "–", "textemdash": "—", "textbullet": "•", "LaTeX": "LaTeX", "TeX": "TeX",
    "textquotesingle": "'", "textquotedbl": '"', "textregistered": "®", "texttrademark": "™",
    "copyright": "©", "textdegree": "°", "S": "§", "P": "¶", "pounds": "£", "euro": "€",
    "textdollar": "$", "textunderscore": "_", "quad": " ", "qquad": " ", "newline": " ",
    "linebreak": " ", "par": " ", "item": "", "hfill": " ", "centering": "", "noindent": "",
}

_MATH = {
    "sim": "~", "times": "×", "approx": "≈", "rightarrow": "→", "to": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "geq": "≥", "ge": "≥", "leq": "≤", "le": "≤", "pm": "±", "cdot": "·",
    "bullet": "•", "mid": "|", "vert": "|", "%": "%", "infty": "∞", "circ": "°", "degree": "°",
    "uparrow": "↑", "downarrow": "↓", "star": "*", "ast": "*", "cdots": "...", "ldots": "...",
    "sum": "Σ", "Delta": "Δ", "mu": "μ", "alpha": "α", "beta": "β", "lambda": "λ", "sigma": "σ",
}

_BOLD = {"textbf", "bf", "bfseries"}
# Commands whose arguments hold no visible text.
_DROP_ARGS = {
    "vspace": 1, "vspace*": 1, "hspace": 1, "hspace*": 1, "color": 1, "label": 1, "phantom": 1,
    "hphantom": 1, "vphantom": 1, "setlength": 2, "addtolength": 2, "raisebox": 1, "rule": 2,
    "fontsize": 2, "includegraphics": 1, "pagecolor": 1, "definecolor": 3, "titlespacing": 4,
    "cite": 1, "ref": 1, "pageref": 1, "footnotemark": 0, "rotatebox": 1,
}
# Commands whose first argument is dropped and later ones kept (\href{url}{text}).
_DROP_FIRST = {"href": 1, "textcolor": 1, "colorbox": 1, "foreignlanguage": 1, "hyperlink": 1}

_ACCENTS = {"'": "́", "`": "̀", "^": "̂", '"': "̈", "~": "̃", "=": "̄", ".": "̇", "c": "̧", "v": "̌", "u": "̆", "H": "̋"}


# Brace arguments that follow the environment name, e.g. \begin{tabular*}{width}{cols}.
_ENV_ARGS = {"tabular": 1, "tabular*": 2, "tabularx": 2, "minipage": 1, "multicols": 1, "array": 1, "longtable": 1}


def _skip_environment_args(s: str, i: int, is_begin: bool) -> int:
    """Skip `{env}` and, for \\begin, the environment's options and layout arguments."""
    n = len(s)

    def skip_ws(j: int) -> int:
        while j < n and s[j] in " \t\n":
            j += 1
        return j

    j = skip_ws(i)
    if j >= n or s[j] != "{":
        return i
    k = match_brace(s, j)
    if k == -1:
        return n
    env = s[j + 1 : k].strip()
    j = k + 1
    if not is_begin:
        return j
    extra = _ENV_ARGS.get(env, 0)
    while True:
        m = skip_ws(j)
        if m < n and s[m] == "[":
            k = match_bracket(s, m)
            if k == -1:
                return n
            j = k + 1
            continue
        if extra and m < n and s[m] == "{":
            k = match_brace(s, m)
            if k == -1:
                return n
            j = k + 1
            extra -= 1
            continue
        return j


def _read_group_or_char(s: str, i: int) -> tuple[str, int]:
    while i < len(s) and s[i] == " ":
        i += 1
    if i < len(s) and s[i] == "{":
        j = match_brace(s, i)
        if j == -1:
            return "", len(s)
        return s[i + 1 : j], j + 1
    if i < len(s):
        return s[i], i + 1
    return "", i


def _convert(s: str, math: bool = False) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 >= n:
                break
            nxt = s[i + 1]
            if nxt == "\\":  # line break, optionally \\[4pt]
                out.append(" ")
                i += 2
                if i < n and s[i] == "*":
                    i += 1
                if i < n and s[i] == "[":
                    k = match_bracket(s, i)
                    i = k + 1 if k != -1 else i
                continue
            if nxt in _ACCENTS and not (nxt.isalpha() and i + 2 < n and s[i + 2].isalpha()):
                base, j = _read_group_or_char(s, i + 2)
                out.append(unicodedata.normalize("NFC", _convert(base) + _ACCENTS[nxt]))
                i = j
                continue
            if nxt in _ESCAPED:
                out.append(_ESCAPED[nxt])
                i += 2
                continue
            m = re.match(r"[A-Za-z@]+\*?", s[i + 1 :])
            if not m:
                i += 2
                continue
            name = m.group(0)
            i += 1 + len(name)
            if math and name in _MATH:
                out.append(_MATH[name])
                continue
            if name in _SYMBOLS:
                out.append(_SYMBOLS[name])
                if i < n and s[i : i + 2] == "{}":
                    i += 2
                continue
            if name in _BOLD:
                j = i
                while j < n and s[j] == " ":
                    j += 1
                if name == "textbf" and j < n and s[j] == "{":
                    k = match_brace(s, j)
                    if k != -1:
                        inner = _convert(s[j + 1 : k], math).strip()
                        out.append(f"**{inner}**" if inner else "")
                        i = k + 1
                continue
            if name in ("begin", "end"):
                i = _skip_environment_args(s, i, name == "begin")
                continue
            if name in _DROP_ARGS or name in _DROP_FIRST:
                drop = _DROP_ARGS.get(name, _DROP_FIRST.get(name, 0))
                j = i
                for _ in range(drop):
                    while j < n and s[j] in " \n":
                        j += 1
                    if j < n and s[j] == "[":
                        k = match_bracket(s, j)
                        j = k + 1 if k != -1 else j
                        while j < n and s[j] in " \n":
                            j += 1
                    if j < n and s[j] == "{":
                        k = match_brace(s, j)
                        j = k + 1 if k != -1 else n
                i = j
                continue
            # Any other command: drop the name, keep the text of its arguments.
            continue
        if c == "{":
            j = match_brace(s, i)
            if j == -1:
                i += 1
                continue
            inner = s[i + 1 : j]
            m = re.match(r"\s*\\(bf|bfseries)\b\s*", inner)
            if m:
                text = _convert(inner[m.end() :], math).strip()
                out.append(f"**{text}**" if text else "")
            else:
                out.append(_convert(inner, math))
            i = j + 1
            continue
        if c == "}":
            i += 1
            continue
        if c == "$" and not math:
            j = i + 1
            while j < n and not (s[j] == "$" and s[j - 1] != "\\"):
                j += 1
            out.append(_convert(s[i + 1 : j], math=True))
            i = j + 1
            continue
        if math and c in "^_":
            i += 1
            continue
        if c == "~":
            out.append(" ")
            i += 1
            continue
        if c == "-" and s.startswith("---", i):
            out.append("—")
            i += 3
            continue
        if c == "-" and s.startswith("--", i):
            out.append("–")
            i += 2
            continue
        if s.startswith("``", i) or s.startswith("''", i):
            out.append('"')
            i += 2
            continue
        if c == "`":
            out.append("'")
            i += 1
            continue
        if c == "&":
            out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def latex_to_plain(fragment: str) -> str:
    """Readable text for a LaTeX fragment, with bold as **x**. Comments must already be masked."""
    text = _convert(fragment)
    text = re.sub(r"\*\*\s*\*\*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    return text


# --- plain text -> LaTeX -------------------------------------------------------

_UNICODE_TO_LATEX = {
    "–": "--", "—": "---", "‒": "--", "―": "---", "−": "-", "‐": "-", "‑": "-",
    "“": "``", "”": "''", "„": "``", "‘": "`", "’": "'", "‚": ",", "′": "'", "″": "''",
    "…": r"\ldots{}", "•": r"\textbullet{}", "·": r"\textperiodcentered{}",
    "×": r"$\times$", "≈": r"$\approx$", "→": r"$\rightarrow$", "←": r"$\leftarrow$",
    "⇒": r"$\Rightarrow$", "≥": r"$\geq$", "≤": r"$\leq$", "±": r"$\pm$", "∞": r"$\infty$",
    "↑": r"$\uparrow$", "↓": r"$\downarrow$", "°": r"\textdegree{}", "€": r"\texteuro{}",
    "£": r"\pounds{}", "₹": "Rs. ", "©": r"\textcopyright{}", "®": r"\textregistered{}",
    "™": r"\texttrademark{}", "§": r"\S{}", "Σ": r"$\Sigma$", "Δ": r"$\Delta$", "μ": r"$\mu$",
    "α": r"$\alpha$", "β": r"$\beta$", "λ": r"$\lambda$", "σ": r"$\sigma$",
    " ": " ", " ": " ", " ": " ", " ": " ", "​": "", "‌": "",
    "‍": "", "﻿": "", "­": "",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}

_ESCAPE = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}",
}


def _fold_char(ch: str) -> str:
    """Characters pdfLaTeX (with T1 or utf8 input) can typeset, or a close ASCII stand-in."""
    if ch in _UNICODE_TO_LATEX:
        return _UNICODE_TO_LATEX[ch]
    code = ord(ch)
    if code < 128:
        return ch
    if 0xC0 <= code <= 0xFF and ch not in "×÷":
        return ch  # Latin-1 letters such as é, ü, ñ are fine
    folded = unicodedata.normalize("NFKD", ch)
    ascii_only = "".join(c for c in folded if ord(c) < 128 and not unicodedata.combining(c))
    return ascii_only  # emoji, CJK and the like are dropped


def _escape_plain(text: str) -> str:
    out: list[str] = []
    for idx, ch in enumerate(text):
        if ch in _ESCAPE:
            out.append(_ESCAPE[ch])
        elif ch == '"':
            prev = text[idx - 1] if idx else " "
            out.append("``" if prev in " ([{\n\t" else "''")
        else:
            folded = _fold_char(ch)
            if folded == ch:
                out.append(ch)
            else:
                # folded symbols are already LaTeX; plain replacements still need escaping
                out.append(folded if "\\" in folded or "$" in folded or folded in ("--", "---", "``", "''", "`", "'") else "".join(_ESCAPE.get(c, c) for c in folded))
    return "".join(out)


def plain_to_latex(text: str) -> str:
    """Safe LaTeX for plain text. `**x**` becomes bold; everything else is escaped."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split("**")
    if len(parts) % 2 == 0:  # unbalanced markers: treat them as plain text
        parts = [text.replace("**", "")]
    out: list[str] = []
    for idx, part in enumerate(parts):
        if not part:
            continue
        escaped = _escape_plain(part)
        if idx % 2 == 1 and part.strip():
            out.append(r"\textbf{" + escaped + "}")
        else:
            out.append(escaped)
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def strip_bold(text: str) -> str:
    return text.replace("**", "")

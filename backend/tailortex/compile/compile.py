"""Compile LaTeX with TeX Live, safely.

- **Engine detection:** pdfLaTeX by default (Overleaf's default), XeLaTeX when the
  template uses fontspec or a class that needs it, LuaLaTeX for Lua templates.
- **Safety:** LaTeX can run shell commands and read files. Documents that try
  are refused before TeX runs, TeX runs with shell escape off and paranoid file
  access, in a fresh temp folder, with a timeout.
- **Results:** the PDF, page count, extracted text (what an ATS reads), how full
  the last page is, and errors with line numbers.
- **Missing packages** are installed on demand with tlmgr (TinyTeX, local only).
"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_TEX_BYTES = 400_000
MAX_FILES_BYTES = 15_000_000
DEFAULT_TIMEOUT = 30.0

_install_lock = threading.Lock()


class UnsafeLatexError(ValueError):
    pass


@dataclass
class CompileError:
    line: int | None
    message: str


@dataclass
class CompileResult:
    ok: bool
    engine: str
    pdf: bytes | None = None
    pages: int = 0
    text: str = ""
    page_fill: float | None = None
    errors: list[CompileError] = field(default_factory=list)
    log_tail: str = ""
    seconds: float = 0.0
    installed: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "engine": self.engine,
            "pages": self.pages,
            "page_fill": self.page_fill,
            "errors": [e.__dict__ for e in self.errors],
            "seconds": round(self.seconds, 2),
        }


# --- finding TeX -------------------------------------------------------------------


def tex_bin_dir() -> Path | None:
    env = os.environ.get("TAILORTEX_TEX_BIN")
    if env and (Path(env) / "pdflatex").exists():
        return Path(env)
    found = shutil.which("pdflatex")
    if found:
        return Path(found).parent
    home = Path.home()
    candidates = [
        home / "Library/TinyTeX/bin/universal-darwin",
        home / ".TinyTeX/bin/x86_64-linux",
        home / ".TinyTeX/bin/aarch64-linux",
        Path("/Library/TeX/texbin"),
        *map(Path, sorted(glob.glob("/usr/local/texlive/*/bin/*"), reverse=True)),
    ]
    for c in candidates:
        if (c / "pdflatex").exists():
            return c
    return None


def tex_available() -> bool:
    return tex_bin_dir() is not None


def missing_tex_files(names: list[str]) -> list[str]:
    """Which of these .cls / .sty files TeX can't find (empty if TeX isn't installed)."""
    bindir = tex_bin_dir()
    if not names or bindir is None or not (bindir / "kpsewhich").exists():
        return []
    try:
        out = subprocess.run([str(bindir / "kpsewhich"), *names], capture_output=True, text=True, timeout=10).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []
    found = {Path(line.strip()).name for line in out.splitlines() if line.strip()}
    return [n for n in names if n not in found]


def _tool(name: str) -> str | None:
    """A poppler tool (pdftotext, pdfinfo) if installed."""
    return shutil.which(name)


# --- engine and safety -------------------------------------------------------------


def detect_engine(tex: str) -> str:
    if re.search(r"\\directlua|\\luaexec|\\begin\s*\{luacode", tex) or re.search(r"\\usepackage(\[[^\]]*\])?\{luacode\}", tex):
        return "lualatex"
    if re.search(r"\\usepackage(\[[^\]]*\])?\{(fontspec|xeCJK|polyglossia|unicode-math)\}", tex) or re.search(r"\\set(main|sans|mono)font", tex):
        return "xelatex"
    if re.search(r"\\documentclass(\[[^\]]*\])?\{(awesome-cv|altacv)\}", tex):
        return "xelatex"
    return "pdflatex"


_UNSAFE = [
    (r"\\write18|\\immediate\s*\\write|\\openout", "writes files or runs shell commands"),
    (r"\\directlua|\\luaexec|\\latelua", "runs Lua code"),
    (r"\\ShellEscape|\\usepackage(\[[^\]]*\])?\{shellesc\}", "runs shell commands"),
    (r"\\input\s*\|?\s*\{?\s*\|", "pipes a shell command into \\input"),
    (r"\\openin|\\read\s*\d|\\readline", "reads files directly"),
    (r"\\(?:input|include|InputIfFileExists|includegraphics|lstinputlisting|verbatiminput|include(?:only)?|subfile|import)\s*(?:\[[^\]]*\])?\s*\{\s*(?:/|~|[A-Za-z]:\\|[^}]*\.\.)", "reads a file outside the project folder"),
    (r"\\catcode\s*`?\\?[\\^%|]", "changes how TeX reads characters"),
]


def safety_check(tex: str) -> list[str]:
    """Reasons this document can't be compiled; empty if it's safe."""
    from ..latex.scan import mask_comments

    masked = mask_comments(tex)
    return [reason for pattern, reason in _UNSAFE if re.search(pattern, masked)]


# --- compiling ---------------------------------------------------------------------


def _safe_name(name: str) -> str | None:
    p = Path(name)
    if p.is_absolute() or ".." in p.parts or name.startswith("~"):
        return None
    return str(p)


def _limit_resources(timeout: float):  # pragma: no cover - runs in the child process
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 5))
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))


def _run_tex(bindir: Path, engine: str, workdir: Path, timeout: float) -> tuple[int, str]:
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env.update({"openin_any": "p", "openout_any": "p", "shell_escape": "f", "max_print_line": "1000"})
    cmd = [str(bindir / engine), "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "-no-shell-escape", "main.tex"]
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, env=env, capture_output=True, timeout=timeout,
            preexec_fn=(lambda: _limit_resources(timeout)) if sys.platform.startswith("linux") else None,
        )
    except subprocess.TimeoutExpired:
        return -1, "Compilation timed out."
    log_path = workdir / "main.log"
    log = log_path.read_text(errors="replace") if log_path.exists() else proc.stdout.decode(errors="replace")
    return proc.returncode, log


def _missing_file(log: str) -> str | None:
    m = re.search(r"! (?:LaTeX Error: )?File `([^']+)' not found", log)
    if m:
        return m.group(1)
    m = re.search(r"! Font [^=]+=([A-Za-z0-9-]+)[^\n]* not loadable: Metric \(TFM\) file not found", log)
    if m:
        return m.group(1) + ".tfm"
    return None


def _install_for(bindir: Path, filename: str) -> str | None:
    """Find and install the TeX Live package that provides filename (TinyTeX only)."""
    if os.environ.get("TAILORTEX_TEX_AUTOINSTALL", "1") != "1":
        return None
    tlmgr = bindir / "tlmgr"
    if not tlmgr.exists():
        return None
    with _install_lock:
        try:
            out = subprocess.run([str(tlmgr), "search", "--global", "--file", "/" + filename], capture_output=True, timeout=120, text=True).stdout
        except (subprocess.TimeoutExpired, OSError):
            return None
        pkgs = re.findall(r"^([A-Za-z0-9_.-]+):\s*$", out, re.MULTILINE)
        if not pkgs:
            return None
        pkg = pkgs[0]
        try:
            subprocess.run([str(tlmgr), "install", pkg], capture_output=True, timeout=300)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return pkg


def _parse_errors(log: str) -> list[CompileError]:
    errors: list[CompileError] = []
    seen: set[str] = set()
    for m in re.finditer(r"^(?:\./)?main\.tex:(\d+): (.+)$", log, re.MULTILINE):
        msg = m.group(2).strip()
        if msg not in seen:
            seen.add(msg)
            errors.append(CompileError(int(m.group(1)), msg))
    if not errors:
        for m in re.finditer(r"^! (.+)$", log, re.MULTILINE):
            msg = m.group(1).strip()
            if msg not in seen:
                seen.add(msg)
                line = re.search(r"^l\.(\d+)", log[m.end() :], re.MULTILINE)
                errors.append(CompileError(int(line.group(1)) if line else None, msg))
    return errors[:5]


def pdf_pages(pdf_path: Path) -> int:
    info = _tool("pdfinfo")
    if info:
        out = subprocess.run([info, str(pdf_path)], capture_output=True, text=True).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
        if m:
            return int(m.group(1))
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


def pdf_text(pdf_path: Path) -> str:
    tool = _tool("pdftotext")
    if tool:
        proc = subprocess.run([tool, "-enc", "UTF-8", str(pdf_path), "-"], capture_output=True)
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace")
    from pypdf import PdfReader

    return "\n".join(p.extract_text() or "" for p in PdfReader(str(pdf_path)).pages)


def page_fill(pdf_path: Path, pages: int) -> float | None:
    """How far down the last page the text reaches, 0..1."""
    tool = _tool("pdftotext")
    if not tool or pages < 1:
        return None
    proc = subprocess.run([tool, "-tsv", "-f", str(pages), "-l", str(pages), str(pdf_path), "-"], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.startswith("level"):
        height = None
        bottom = 0.0
        for row in proc.stdout.splitlines()[1:]:
            cols = row.split("\t")
            if len(cols) < 12:
                continue
            if cols[0] == "1":
                height = float(cols[9])
            elif cols[0] == "5" and cols[11].strip():
                bottom = max(bottom, float(cols[7]) + float(cols[9]))
        if height:
            return round(min(1.0, bottom / height), 3)
    proc = subprocess.run([tool, "-bbox", "-f", str(pages), "-l", str(pages), str(pdf_path), "-"], capture_output=True, text=True)
    if proc.returncode == 0:
        page = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', proc.stdout)
        ys = [float(y) for y in re.findall(r'yMax="([\d.]+)"', proc.stdout)]
        if page and ys:
            return round(min(1.0, max(ys) / float(page.group(2))), 3)
    return None


def compile_latex(
    tex: str,
    files: dict[str, bytes] | None = None,
    engine: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> CompileResult:
    """Compile a document. Raises UnsafeLatexError for documents that aren't allowed."""
    start = time.monotonic()
    engine = engine or detect_engine(tex)
    if len(tex.encode()) > MAX_TEX_BYTES:
        raise UnsafeLatexError(f"The .tex file is larger than {MAX_TEX_BYTES // 1000} KB.")
    reasons = safety_check(tex)
    for name, data in (files or {}).items():
        if name.endswith((".tex", ".cls", ".sty")):
            reasons += [f"{name}: {r}" for r in safety_check(data.decode(errors="replace"))]
    if reasons:
        raise UnsafeLatexError("This document can't be compiled because it " + "; ".join(dict.fromkeys(reasons)) + ".")
    if sum(len(v) for v in (files or {}).values()) > MAX_FILES_BYTES:
        raise UnsafeLatexError("The project files are too large.")

    bindir = tex_bin_dir()
    if bindir is None:
        return CompileResult(False, engine, errors=[CompileError(None, "LaTeX (TeX Live) isn't installed on the server.")], seconds=time.monotonic() - start)

    installed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="tailortex-") as tmp:
        work = Path(tmp)
        (work / "main.tex").write_text(tex)
        for name, data in (files or {}).items():
            safe = _safe_name(name)
            if not safe or safe == "main.tex":
                continue
            dest = work / safe
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        code, log = 0, ""
        for _attempt in range(6):
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 1:
                code, log = -1, "Compilation timed out."
                break
            code, log = _run_tex(bindir, engine, work, remaining)
            if code != 0:
                missing = _missing_file(log)
                if missing and len(installed) < 3:
                    pkg = _install_for(bindir, missing)
                    if pkg and pkg not in installed:
                        installed.append(pkg)
                        continue
                break
            if "Rerun to get" in log or "Label(s) may have changed" in log:
                continue
            break

        pdf_path = work / "main.pdf"
        elapsed = time.monotonic() - start
        if code != 0 or not pdf_path.exists():
            errors = _parse_errors(log) or [CompileError(None, "Compilation timed out." if code == -1 else "LaTeX failed without a clear error.")]
            return CompileResult(False, engine, errors=errors, log_tail=log[-4000:], seconds=elapsed, installed=installed)
        pages = pdf_pages(pdf_path)
        return CompileResult(
            ok=True,
            engine=engine,
            pdf=pdf_path.read_bytes(),
            pages=pages,
            text=pdf_text(pdf_path),
            page_fill=page_fill(pdf_path, pages),
            log_tail=log[-4000:],
            seconds=time.monotonic() - start,
            installed=installed,
        )


_semaphore: asyncio.Semaphore | None = None


async def compile_async(tex: str, files: dict[str, bytes] | None = None, engine: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> CompileResult:
    """compile_latex in a worker thread, with at most TAILORTEX_MAX_COMPILES running at once."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(int(os.environ.get("TAILORTEX_MAX_COMPILES", "3")))
    async with _semaphore:
        return await asyncio.to_thread(compile_latex, tex, files, engine, timeout)

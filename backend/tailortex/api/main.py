"""TailorTeX REST API.

Model keys arrive in the request body, are used for that request only, and are
never stored or logged. Error logs record the path, never the body.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..ats.health import apply_lint_fix, document_class, lint_source
from ..compile.compile import UnsafeLatexError, compile_async, detect_engine, missing_tex_files, tex_available
from ..latex.parse import parse_resume
from ..learn.bandit import Bandit
from ..learn.feedback import change_reward, run_reward
from ..learn.style import StyleMemory, StyleRules
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import STYLE_SYSTEM
from ..llm.providers import PROVIDERS, detect_provider, recommended_model
from ..ops import Op
from ..pipeline.tailor import TailorError, TailorInput, rebuild, tailor
from ..types import EvidenceItem, JobAnalysis
from .github import GitHubError, import_repos, list_repos

ROOT = Path(__file__).resolve().parents[3]
PKG = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend" / "dist"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger("tailortex")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="TailorTeX", version="0.1.0", description="Tailor a LaTeX resume to a job description without breaking the template or inventing anything.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("TAILORTEX_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

MAX_TEX = 400_000
MAX_JD = 40_000


# --- rate limiting (per client IP, in memory) ------------------------------------------

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
LIMITS = {"tailor": (8, 60), "compile": (40, 60), "github": (20, 60), "models": (30, 60), "feedback": (60, 60)}


def rate_limit(request: Request, bucket: str) -> None:
    n, window = LIMITS[bucket]
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    q = _hits[(ip, bucket)]
    now = time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, f"Too many requests. Try again in {int(window - (now - q[0])) + 1} seconds.")
    q.append(now)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # never log bodies (they can hold keys)
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server."}, status_code=500)


# --- models ------------------------------------------------------------------------------


class KeyRequest(BaseModel):
    key: str | None = Field(default=None, max_length=400)
    provider: str | None = None
    model: str | None = None


class TexRequest(BaseModel):
    tex: str = Field(max_length=MAX_TEX)


class LintFixRequest(TexRequest):
    fix: str


class TailorRequest(KeyRequest):
    tex: str = Field(max_length=MAX_TEX)
    jd: str = Field(max_length=MAX_JD)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=60)
    skills: list[str] = Field(default_factory=list, max_length=80)
    candidates: int = Field(default=1, ge=1, le=3)
    compile: bool = True
    page_limit: int | None = Field(default=None, ge=1, le=4)
    user: str | None = Field(default=None, max_length=64)


class RebuildRequest(BaseModel):
    tex: str = Field(max_length=MAX_TEX)
    ops: list[Op] = Field(max_length=200)
    analysis: JobAnalysis
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=60)
    skills: list[str] = Field(default_factory=list, max_length=80)
    compile: bool = True
    page_limit: int | None = Field(default=None, ge=1, le=4)


class GitHubRequest(BaseModel):
    username: str = Field(max_length=39)
    repos: list[str] = Field(default_factory=list, max_length=8)


class Decision(BaseModel):
    change_id: int
    action: str = Field(pattern="^(kept|reverted|edited|regenerated)$")
    suggested: str = Field(default="", max_length=2000)
    final: str = Field(default="", max_length=2000)


class FeedbackRequest(KeyRequest):
    run_id: str = Field(max_length=40)
    context: str = Field(max_length=80)
    arm: str = Field(max_length=40)
    reward: float = Field(ge=0, le=1)
    user: str | None = Field(default=None, max_length=64)
    decisions: list[Decision] = Field(default_factory=list, max_length=200)


# --- helpers -------------------------------------------------------------------------------


def server_key() -> tuple[str | None, str | None, str | None]:
    key = os.environ.get("TAILORTEX_API_KEY") or None
    provider = os.environ.get("TAILORTEX_PROVIDER") or (detect_provider(key)[0] if key else None)
    return key, provider, os.environ.get("TAILORTEX_MODEL") or None


def make_llm(req: KeyRequest) -> LLMClient:
    key = (req.key or "").strip()
    provider = req.provider
    model = req.model
    if not key:
        skey, sprov, smodel = server_key()
        if not skey:
            raise HTTPException(400, "Paste a model API key first (Gemini and Groq have free tiers).")
        key, provider, model = skey, provider or sprov, model or smodel
    provider = provider or detect_provider(key)[0]
    if provider not in PROVIDERS:
        raise HTTPException(400, "Couldn't tell which provider this key is for. Pick the provider from the list.")
    return LLMClient(provider=provider, key=key, model=model or "")


def evidence_with_skills(evidence: list[EvidenceItem], skills: list[str]) -> list[EvidenceItem]:
    items = [e for e in evidence if e.full_text().strip()]
    clean = [s.strip() for s in skills if s.strip()][:80]
    if clean:
        items.append(EvidenceItem(id="skills", source="skill", title="Skills the candidate can defend in an interview", skills=clean))
    for e in items:
        e.text = e.text[:4000]
    return items


def lint(doc, tex: str, engine: str) -> list[dict]:
    issues = [i.to_dict() for i in lint_source(doc, engine)]
    cls = document_class(tex)
    if cls and missing_tex_files([f"{cls}.cls"]):
        issues.append({
            "id": "custom_class", "severity": "warn", "fixable": False,
            "message": f"Your resume uses the '{cls}' class, which lives in a separate file in your Overleaf project. "
            "TailorTeX can still tailor it, but can't compile the PDF here; open the result in Overleaf to compile it.",
        })
    return issues


def outline(tex: str) -> dict:
    doc = parse_resume(tex)
    engine = detect_engine(tex)

    def block(b):
        return {"id": b.id, "kind": b.kind, "text": b.text, "label": b.label, "locked": b.locked, "lock_reason": b.lock_reason}

    return {
        "profile": doc.profile,
        "name": doc.name(),
        "engine": engine,
        "bullet_budget": doc.bullet_budget,
        "sections": [
            {
                "id": s.id, "title": s.title, "kind": s.kind, "locked": s.locked,
                "blocks": [block(b) for b in s.blocks],
                "entries": [{"id": e.id, "heading": e.heading, "bullets": [block(b) for b in e.bullets]} for e in s.entries],
            }
            for s in doc.sections
        ],
        "stats": {
            "sections": len(doc.sections),
            "bullets": sum(len(e.bullets) for s in doc.sections for e in s.entries),
            "editable": len(doc.editable_blocks()),
        },
        "lint": lint(doc, tex, engine),
    }


# --- endpoints --------------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"ok": True, "tex": tex_available()}


@app.get("/api/config")
async def config():
    key, provider, model = server_key()
    return {
        "server_key": bool(key),
        "server_provider": provider if key else None,
        "server_model": model if key else None,
        "tex": tex_available(),
        "providers": [{"id": p.id, "label": p.label, "key_url": p.key_url, "free_tier": p.free_tier} for p in PROVIDERS.values()],
    }


@app.post("/api/providers/detect")
async def detect(req: KeyRequest):
    provider, candidates = detect_provider(req.key or "")
    return {"provider": provider, "candidates": candidates}


@app.post("/api/models")
async def models(req: KeyRequest, request: Request):
    rate_limit(request, "models")
    llm = make_llm(req)
    try:
        found = await llm.list_models()
    except LLMError as e:
        raise HTTPException(401 if e.kind == "auth" else 502, str(e)) from None
    ids = [m.id for m in found]
    _, _, smodel = server_key()
    rec = (smodel if not req.key and smodel in ids else None) or recommended_model(llm.provider, ids)
    return {
        "provider": llm.provider,
        "models": [m.__dict__ for m in found],
        "recommended": rec,
    }


@app.get("/api/sample")
async def sample():
    data = json.loads((PKG / "samples" / "evidence.json").read_text())
    return {
        "tex": (PKG / "templates" / "jake" / "resume.tex").read_text(),
        "jd": (PKG / "samples" / "jd_backend.txt").read_text(),
        "evidence": data["evidence"],
        "skills": data["skills"],
    }


@app.get("/api/template")
async def template():
    return {"tex": (PKG / "templates" / "jake" / "resume.tex").read_text()}


@app.post("/api/parse")
async def parse(req: TexRequest):
    return outline(req.tex)


@app.post("/api/lint/fix")
async def lint_fix(req: LintFixRequest):
    fixed = apply_lint_fix(req.tex, req.fix)
    return {"tex": fixed, "outline": outline(fixed)}


@app.post("/api/compile")
async def compile_endpoint(req: TexRequest, request: Request):
    rate_limit(request, "compile")
    if not tex_available():
        raise HTTPException(503, "LaTeX isn't installed on this server.")
    try:
        r = await compile_async(req.tex)
    except UnsafeLatexError as e:
        raise HTTPException(400, str(e)) from None
    return {**r.summary(), "pdf": base64.b64encode(r.pdf).decode() if r.pdf else None, "log_tail": r.log_tail[-1500:] if not r.ok else ""}


@app.post("/api/tailor")
async def tailor_endpoint(req: TailorRequest, request: Request):
    rate_limit(request, "tailor")
    llm = make_llm(req)
    if not llm.model:
        try:
            ids = [m.id for m in await llm.list_models()]
        except LLMError as e:
            raise HTTPException(401 if e.kind == "auth" else 502, str(e)) from None
        llm.model = recommended_model(llm.provider, ids) or ""
    if not req.jd.strip():
        raise HTTPException(400, "Paste the job description.")
    inp = TailorInput(
        tex=req.tex, jd=req.jd, evidence=evidence_with_skills(req.evidence, req.skills),
        candidates=req.candidates, compile_pdf=req.compile, page_limit=req.page_limit, user=req.user,
    )
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await queue.put(await tailor(inp, llm, emit))
        except LLMError as e:
            await queue.put({"type": "error", "kind": e.kind, "message": str(e)})
        except (TailorError, UnsafeLatexError) as e:
            await queue.put({"type": "error", "kind": "input", "message": str(e)})
        except Exception:
            log.exception("Tailoring failed")
            await queue.put({"type": "error", "kind": "server", "message": "Something went wrong while tailoring. Please try again."})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'start', 'provider': llm.provider, 'model': llm.model})}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/rebuild")
async def rebuild_endpoint(req: RebuildRequest, request: Request):
    rate_limit(request, "compile")
    try:
        return await rebuild(req.tex, req.ops, req.analysis, evidence_with_skills(req.evidence, req.skills), req.compile, req.page_limit)
    except UnsafeLatexError as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/evidence/github")
async def github_repos(req: GitHubRequest, request: Request):
    rate_limit(request, "github")
    try:
        if req.repos:
            return {"evidence": [e.model_dump() for e in await import_repos(req.username, req.repos)]}
        return {"repos": await list_repos(req.username)}
    except GitHubError as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest, request: Request):
    """Keep / revert / edit decisions on each change: rewards the bandit and updates style memory."""
    rate_limit(request, "feedback")
    rewards = [change_reward(d.action, d.suggested, d.final) for d in req.decisions]  # type: ignore[arg-type]
    total = run_reward(rewards, req.reward)
    Bandit().update(req.context, req.arm, total, req.user)
    distilled = None
    if req.user:
        style = StyleMemory()
        kept = [d.suggested for d in req.decisions if d.action == "kept" and d.suggested][:10]
        edits = [(d.suggested, d.final) for d in req.decisions if d.action == "edited" and d.final]
        due = style.record(req.user, kept, edits)
        if due and (req.key or server_key()[0]):
            try:
                llm = make_llm(req)
                pairs = style.pairs(req.user)
                prompt = "\n".join(f"Suggested: {a}\nUser's version: {b}" for a, b in pairs[-12:])
                rules = await llm.complete(STYLE_SYSTEM, prompt, StyleRules)
                style.set_rules(req.user, rules.rules)
                distilled = rules.rules
            except (LLMError, HTTPException):
                distilled = None
    return {"reward": round(total, 4), "style_rules": distilled}


@app.get("/api/learning")
async def learning():
    return {"bandit": Bandit().stats()}


# --- the built frontend (production: `make start`) ----------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

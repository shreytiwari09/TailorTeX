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
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..ats.health import apply_lint_fix, document_class, lint_source
from ..db import engine as db_engine
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
from ..evidence.extract import EXTRACT_SYSTEM, POSTS_SYSTEM, archive_items, extract_plain, extract_with_model, posts_plain
from ..evidence.github import GitHubError, best_repos, import_repos, list_repos
from ..evidence.links import classify, split_links
from ..evidence.notes import notes_to_evidence
from ..evidence.sources import SourceError, fetch_page, html_to_text, pdf_to_text, read_linkedin_archive

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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if db_engine.enabled():
        try:
            await db_engine.init_db()
            log.info("Accounts and storage: PostgreSQL")
        except Exception:
            log.exception("Couldn't reach the database; accounts are off until it's back")
    yield
    await db_engine.dispose()


app = FastAPI(
    title="TailorTeX", version="0.2.0", lifespan=lifespan,
    description="Tailor a LaTeX resume to a job description without breaking the template or inventing anything.",
)
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
LIMITS = {"auth": (20, 60), "tailor": (8, 60), "compile": (40, 60), "github": (20, 60), "evidence": (12, 60), "models": (30, 60), "feedback": (60, 60)}


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
    notes: str = Field(default="", max_length=6000)
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
    notes: str = Field(default="", max_length=6000)
    compile: bool = True
    page_limit: int | None = Field(default=None, ge=1, le=4)


class ForgetRequest(BaseModel):
    user: str = Field(min_length=1, max_length=64)


class GitHubRequest(BaseModel):
    username: str = Field(max_length=39)
    repos: list[str] = Field(default_factory=list, max_length=8)


class ProfileRequest(KeyRequest):
    kind: str = Field(pattern="^(linkedin|linkedin_posts|portfolio)$")
    pdf_base64: str | None = Field(default=None, max_length=7_000_000)
    zip_base64: str | None = Field(default=None, max_length=28_000_000)
    text: str | None = Field(default=None, max_length=60_000)
    url: str | None = Field(default=None, max_length=500)


class LinksRequest(KeyRequest):
    links: list[str] = Field(min_length=1, max_length=10)


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


def evidence_with_skills(evidence: list[EvidenceItem], skills: list[str], notes: str = "") -> list[EvidenceItem]:
    """Everything the user told us about themselves, as evidence: imported items, notes, confirmed skills."""
    items = [e for e in evidence if e.full_text().strip()] + notes_to_evidence(notes)
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
        "notes": data.get("notes", ""),
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


async def ensure_model(llm: LLMClient) -> None:
    """Pick the provider's recommended model when none was chosen."""
    if llm.model:
        return
    try:
        ids = [m.id for m in await llm.list_models()]
    except LLMError as e:
        raise HTTPException(401 if e.kind == "auth" else 502, str(e)) from None
    llm.model = recommended_model(llm.provider, ids) or ""


def stream_tailoring(inp: TailorInput, llm: LLMClient, ranker=None, on_result=None) -> StreamingResponse:
    """Run a tailoring and stream its progress as server-sent events; the last event is the result.

    on_result(result) may add to the result (for example the saved run's ID) before it's sent.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            result = await tailor(inp, llm, emit, ranker=ranker)
            if on_result is not None:
                try:
                    await on_result(result)
                except Exception:
                    log.exception("Saving the run failed")
                    result.setdefault("warnings", []).append("This resume couldn't be saved to your history.")
            await queue.put(result)
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


@app.post("/api/tailor")
async def tailor_endpoint(req: TailorRequest, request: Request):
    """The guest (stateless) tailoring: everything comes in the request, nothing is stored."""
    rate_limit(request, "tailor")
    llm = make_llm(req)
    await ensure_model(llm)
    if not req.jd.strip():
        raise HTTPException(400, "Paste the job description.")
    inp = TailorInput(
        tex=req.tex, jd=req.jd, evidence=evidence_with_skills(req.evidence, req.skills, req.notes),
        candidates=req.candidates, compile_pdf=req.compile, page_limit=req.page_limit, user=req.user,
    )
    return stream_tailoring(inp, llm)


@app.post("/api/rebuild")
async def rebuild_endpoint(req: RebuildRequest, request: Request):
    rate_limit(request, "compile")
    try:
        return await rebuild(req.tex, req.ops, req.analysis, evidence_with_skills(req.evidence, req.skills, req.notes), req.compile, req.page_limit)
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


class _Extractor:
    """Runs extraction for one request: the user's model when there's a key, a plain split otherwise."""

    def __init__(self, req: KeyRequest):
        self.req = req
        self.has_key = bool((req.key or "").strip() or server_key()[0])
        self.llm: LLMClient | None = None
        self.notes: list[str] = []

    async def model(self) -> LLMClient | None:
        if not self.has_key:
            return None
        if self.llm is None:
            self.llm = make_llm(self.req)
            if not self.llm.model:
                self.llm.model = recommended_model(self.llm.provider, [m.id for m in await self.llm.list_models()]) or ""
        return self.llm

    async def run(self, text: str, source: str, prefix: str, url: str | None = None, posts: bool = False) -> list[EvidenceItem]:
        try:
            m = await self.model()
            if m is not None:
                return await extract_with_model(m, text, source, prefix, url, POSTS_SYSTEM if posts else EXTRACT_SYSTEM)
            self._note("Read without a model. Add a model key in step 1 for a cleaner breakdown into roles, projects and skills.")
        except LLMError as e:
            self._note(f"The model couldn't read it ({e}), so a simpler split was used.")
        return posts_plain(text, prefix) if posts else extract_plain(text, source, prefix, url)

    def _note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)


@app.post("/api/evidence/links")
async def links_evidence(req: LinksRequest, request: Request):
    """Paste your links and you're done: GitHub profiles and repos, portfolio sites. LinkedIn links get a one-step
    instruction instead, because LinkedIn doesn't let apps read profiles."""
    rate_limit(request, "evidence")
    ex = _Extractor(req)

    async def one(link: str) -> dict:
        kind, info = classify(link)
        out: dict = {"link": link, "kind": kind, "evidence": [], "note": None, "error": None, "url": info.get("url")}
        try:
            if kind == "github_user":
                items = await best_repos(info["user"])
                out["note"] = f"Added {len(items)} of your top repositories. Remove any you don't want below."
            elif kind == "github_repo":
                items = await import_repos(info["user"], [info["repo"]])
                if not items:
                    raise GitHubError(f"Couldn't find the public repository {info['user']}/{info['repo']}.")
                out["note"] = "Added this repository."
            elif kind == "portfolio":
                url, page = await fetch_page(info["url"])
                text = html_to_text(page)
                if len(text) < 80:
                    raise SourceError("There's almost no text on that page; it may be built with JavaScript we can't run. Paste its text under More instead.")
                items = await ex.run(text, "portfolio", "pf", url)
                out["note"] = f"Found {len(items)} item{'s' if len(items) != 1 else ''} on your site."
            elif kind == "linkedin":
                out["note"] = "LinkedIn doesn't let apps read profiles from a link. Open it, click More → Save to PDF, and drop the file below."
                return out
            else:
                out["error"] = "That doesn't look like a link."
                return out
            out["evidence"] = [e.model_dump() for e in items]
        except (GitHubError, SourceError) as e:
            out["error"] = str(e)
        return out

    results = await asyncio.gather(*(one(link) for link in split_links(" ".join(req.links))[:8]))
    return {"results": list(results), "notes": ex.notes}


@app.post("/api/evidence/profile")
async def profile_evidence(req: ProfileRequest, request: Request):
    """LinkedIn (data archive ZIP, "Save to PDF", pasted profile text or pasted posts) or a portfolio (URL or text)
    -> evidence items. `replaces` lists the ID prefixes of earlier imports this one supersedes."""
    rate_limit(request, "evidence")

    def decode(b64: str) -> bytes:
        try:
            return base64.b64decode(b64, validate=False)
        except ValueError:
            raise HTTPException(400, "That file couldn't be read.") from None

    ex = _Extractor(req)
    notes = ex.notes
    extract = ex.run

    try:
        # LinkedIn data archive: structured files, plus posts read by the model.
        if req.kind == "linkedin" and req.zip_base64:
            archive = read_linkedin_archive(decode(req.zip_base64))
            items, skills, posts_text = archive_items(archive)
            post_items = await extract(posts_text, "linkedin", "lp", posts=True) if posts_text else []
            n_posts = len([r for r in archive.get("shares", []) if r.get("sharecommentary")])
            summary = f"Read {len(items)} profile items, {len(skills)} skills and {n_posts} posts ({len(post_items)} about your work)."
            return {"evidence": [e.model_dump() for e in items + post_items], "skills": skills, "replaces": ["li", "la", "lp"],
                    "used_model": ex.llm is not None, "note": " ".join([summary, *notes])}

        if req.kind == "linkedin_posts":
            text = (req.text or "").strip()[:30_000]
            if len(text) < 60:
                raise HTTPException(400, "Paste the text of one or more of your posts.")
            items = await extract(text, "linkedin", "pp", posts=True)  # pasted posts add up across pastes
            return {"evidence": [e.model_dump() for e in items], "skills": [], "replaces": [], "used_model": ex.llm is not None,
                    "note": " ".join([f"Found {len(items)} post{'s' if len(items) != 1 else ''} about your work.", *notes])}

        url = None
        if req.text and req.text.strip():
            text = req.text.strip()[:30_000]
        elif req.kind == "linkedin" and req.pdf_base64:
            text = pdf_to_text(decode(req.pdf_base64))
        elif req.kind == "portfolio" and req.url:
            url, page = await fetch_page(req.url)
            text = html_to_text(page)
        else:
            raise HTTPException(400, "Upload your LinkedIn PDF or archive, give your portfolio's address, or paste the text.")
    except SourceError as e:
        raise HTTPException(400, str(e)) from None
    if len(text) < 80:
        hint = " Your portfolio may be built with JavaScript that we can't run; paste its text instead." if req.kind == "portfolio" else ""
        raise HTTPException(400, "There's almost no text to read there." + hint)

    prefix = "li" if req.kind == "linkedin" else "pf"
    items = await extract(text, req.kind, prefix, url)
    return {"evidence": [e.model_dump() for e in items], "skills": [], "replaces": ["li", "la"] if prefix == "li" else ["pf"],
            "used_model": ex.llm is not None,
            "note": " ".join([f"Found {len(items)} item{'s' if len(items) != 1 else ''}, each checked against the source.", *notes])}


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


@app.post("/api/forget")
async def forget(req: ForgetRequest):
    """Delete what the server learned from this device: its style memory and its own strategy statistics."""
    removed_style = StyleMemory().forget(req.user)
    removed_bandit = Bandit().forget(req.user)
    return {"deleted": removed_style or removed_bandit}


@app.get("/api/learning")
async def learning():
    return {"bandit": Bandit().stats()}


# --- signed-in product routes (accounts, profile, context, saved resumes) ---------------------

from . import account  # noqa: E402  (it uses helpers defined above)

app.include_router(account.router)


# --- the built frontend (production: `make start`) ----------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

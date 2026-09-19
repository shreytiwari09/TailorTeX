"""Signed-in product: accounts, the person's profile and context, and saved resumes.

Sessions are HttpOnly cookies (only a hash of the token is stored). Everything here needs
DATABASE_URL; without it these routes answer 503 and the guest flow keeps working.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..compile.compile import UnsafeLatexError
from ..db import engine, repo
from ..db.google import GoogleAuthError, client_id, verify
from ..db.models import Profile
from ..db.rank import make_ranker
from ..evidence.github import GitHubError, best_repos
from ..evidence.links import classify
from ..evidence.sources import SourceError, fetch_page, html_to_text, pdf_to_text
from ..learn.bandit import Bandit
from ..learn.style import StyleMemory
from ..llm.client import LLMClient, LLMError
from ..llm.providers import PROVIDERS, detect_provider
from ..ops import Op
from ..pipeline.tailor import TailorInput, rebuild
from ..types import EvidenceItem, JobAnalysis
from . import main as core

router = APIRouter(prefix="/api")
COOKIE = "tt_session"
COOKIE_AGE = 60 * 60 * 24 * 30


# --- plumbing --------------------------------------------------------------------------------


async def db_session() -> AsyncIterator[AsyncSession]:
    if not engine.enabled():
        raise HTTPException(503, "Accounts aren't enabled on this server (no database).")
    async with engine.sessions()() as db:
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(COOKIE)


async def current(request: Request, db: AsyncSession = Depends(db_session)) -> Profile:
    profile = await repo.profile_for_token(db, _token(request))
    if profile is None:
        raise HTTPException(401, "Sign in first.")
    return profile


def _set_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, max_age=COOKIE_AGE, httponly=True, samesite="lax", secure=secure, path="/")


def llm_for(profile: Profile) -> LLMClient:
    """The user's saved key, else the server's shared key."""
    key = repo.model_key(profile)
    if key:
        provider = profile.model_provider or detect_provider(key)[0]
        if provider in PROVIDERS:
            return LLMClient(provider=provider, key=key, model=profile.model_name or "")
    return core.make_llm(core.KeyRequest())


def _extractor(profile: Profile) -> core._Extractor:
    key = repo.model_key(profile)
    return core._Extractor(core.KeyRequest(key=key, provider=profile.model_provider, model=profile.model_name) if key else core.KeyRequest())


# --- accounts ----------------------------------------------------------------------------------


class GoogleIn(BaseModel):
    credential: str = Field(max_length=5000)


class SignUpIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    full_name: str = Field(default="", max_length=200)


class SignInIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


@router.get("/auth/config")
async def auth_config():
    return {"accounts": engine.enabled(), "google_client_id": client_id()}


@router.post("/auth/google")
async def auth_google(body: GoogleIn, request: Request, response: Response, db: AsyncSession = Depends(db_session)):
    core.rate_limit(request, "auth")
    try:
        claims = await verify(body.credential)
    except GoogleAuthError as e:
        raise HTTPException(401, str(e)) from None
    profile, token, created = await repo.sign_in_google(db, claims)
    _set_cookie(request, response, token)
    return {"created": created, "profile": await repo.profile_payload(db, profile)}


@router.post("/auth/signup")
async def auth_signup(body: SignUpIn, request: Request, response: Response, db: AsyncSession = Depends(db_session)):
    core.rate_limit(request, "auth")
    try:
        profile, token = await repo.sign_up(db, body.email, body.password, body.full_name)
    except repo.AuthError as e:
        raise HTTPException(400, str(e)) from None
    _set_cookie(request, response, token)
    return {"created": True, "profile": await repo.profile_payload(db, profile)}


@router.post("/auth/signin")
async def auth_signin(body: SignInIn, request: Request, response: Response, db: AsyncSession = Depends(db_session)):
    core.rate_limit(request, "auth")
    try:
        profile, token = await repo.sign_in(db, body.email, body.password)
    except repo.AuthError as e:
        raise HTTPException(401, str(e)) from None
    _set_cookie(request, response, token)
    return {"created": False, "profile": await repo.profile_payload(db, profile)}


@router.post("/auth/signout")
async def auth_signout(request: Request, response: Response, db: AsyncSession = Depends(db_session)):
    token = _token(request)
    if token:
        await repo.sign_out(db, token)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def auth_me(request: Request):
    if not engine.enabled():
        return {"signed_in": False, "accounts": False}
    async with engine.sessions()() as db:
        profile = await repo.profile_for_token(db, _token(request))
        payload = await repo.profile_payload(db, profile) if profile else None
        await db.commit()
    return {"signed_in": payload is not None, "accounts": True, "profile": payload}


# --- profile -----------------------------------------------------------------------------------


class DetailsIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    public_email: str | None = Field(default=None, max_length=320)
    links: dict[str, str] | None = None
    onboarded: bool | None = None


class ResumeIn(BaseModel):
    tex: str = Field(max_length=core.MAX_TEX)


class ModelIn(BaseModel):
    provider: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=400)


class NotesIn(BaseModel):
    notes: str = Field(max_length=6000)


class SkillsIn(BaseModel):
    skills: list[str] = Field(max_length=200)


@router.get("/profile")
async def get_profile(profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    return await repo.profile_payload(db, profile)


@router.put("/profile")
async def put_profile(body: DetailsIn, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    await repo.update_details(db, profile, body.model_dump(exclude_none=True))
    return await repo.profile_payload(db, profile)


@router.put("/profile/resume")
async def put_resume(body: ResumeIn, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    await repo.set_resume(db, profile, body.tex)
    return {"outline": core.outline(body.tex) if body.tex.strip() else None}


@router.put("/profile/model")
async def put_model(body: ModelIn, request: Request, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    """Save the provider, model and (optionally new) key. A new key is checked with the provider first."""
    core.rate_limit(request, "models")
    key = (body.key or "").strip() or repo.model_key(profile)
    if not key:
        raise HTTPException(400, "Paste your model API key.")
    provider = body.provider or detect_provider(key)[0]
    if provider not in PROVIDERS:
        raise HTTPException(400, "Couldn't tell which provider this key is for. Pick the provider.")
    llm = LLMClient(provider=provider, key=key)
    try:
        models = await llm.list_models()
    except LLMError as e:
        raise HTTPException(401 if e.kind == "auth" else 502, str(e)) from None
    ids = [m.id for m in models]
    model = body.model if body.model in ids else core.recommended_model(provider, ids)
    try:
        repo.set_model(profile, provider, model, body.key.strip() if body.key else None)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from None
    return {"model": repo.model_info(profile), "models": [m.__dict__ for m in models], "recommended": core.recommended_model(provider, ids)}


@router.delete("/profile/model")
async def delete_model(profile: Profile = Depends(current)):
    repo.clear_model(profile)
    return {"model": repo.model_info(profile)}


@router.delete("/profile")
async def delete_profile(response: Response, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    user = str(profile.id)
    await repo.delete_profile(db, profile)
    StyleMemory().forget(user)
    Bandit().forget(user)
    response.delete_cookie(COOKIE, path="/")
    return {"deleted": True}


# --- context (the knowledge base) ----------------------------------------------------------------


class LinksIn(BaseModel):
    github: str | None = Field(default=None, max_length=300)
    portfolio: str | None = Field(default=None, max_length=500)


class LinkedInIn(BaseModel):
    pdf_base64: str | None = Field(default=None, max_length=7_000_000)
    text: str | None = Field(default=None, max_length=60_000)


class EntryIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    text: str | None = Field(default=None, max_length=4000)
    skills: list[str] | None = Field(default=None, max_length=40)


@router.get("/profile/context")
async def get_context(profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    return {"entries": [e.model_dump() for e in await repo.list_context(db, profile)], "notes": profile.notes, "skills": profile.skills or []}


@router.post("/profile/context/links")
async def add_links(body: LinksIn, request: Request, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    """Read the GitHub and portfolio links into context entries (a fresh read replaces the previous one)."""
    core.rate_limit(request, "evidence")
    ex = _extractor(profile)
    results = []
    links = dict(profile.links or {})
    for kind, raw in (("github", body.github), ("portfolio", body.portfolio)):
        if not raw or not raw.strip():
            continue
        link = raw.strip()
        if kind == "github" and "github.com" not in link.lower():
            link = f"github.com/{link.lstrip('@')}"
        found, info = classify(link)
        out = {"source": kind, "link": link, "added": 0, "error": None}
        try:
            if kind == "github":
                if found not in ("github_user", "github_repo"):
                    raise GitHubError("That doesn't look like a GitHub profile link.")
                items = await best_repos(info["user"]) if found == "github_user" else await core.import_repos(info["user"], [info["repo"]])
                saved = await repo.replace_source(db, profile, "github", items)
            else:
                if found != "portfolio":
                    raise SourceError("That doesn't look like a website address.")
                url, page = await fetch_page(info["url"])
                text = html_to_text(page)
                if len(text) < 80:
                    raise SourceError("There's almost no text on that page; it may need JavaScript. Paste its text under notes instead.")
                saved = await repo.replace_source(db, profile, "portfolio", await ex.run(text, "portfolio", "pf", url), url)
            out["added"] = len(saved)
            links[kind] = raw.strip()
        except (GitHubError, SourceError) as e:
            out["error"] = str(e)
        results.append(out)
    profile.links = links
    return {"results": results, "notes": ex.notes, "entries": [e.model_dump() for e in await repo.list_context(db, profile)]}


@router.post("/profile/context/linkedin")
async def add_linkedin(body: LinkedInIn, request: Request, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    core.rate_limit(request, "evidence")
    try:
        if body.text and body.text.strip():
            text = body.text.strip()[:30_000]
        elif body.pdf_base64:
            text = pdf_to_text(base64.b64decode(body.pdf_base64, validate=False))
        else:
            raise HTTPException(400, "Upload your LinkedIn PDF (More → Save to PDF on your profile).")
    except (SourceError, ValueError) as e:
        raise HTTPException(400, str(e) if isinstance(e, SourceError) else "That file couldn't be read.") from None
    if len(text) < 80:
        raise HTTPException(400, "There's almost no text in that file.")
    ex = _extractor(profile)
    saved = await repo.replace_source(db, profile, "linkedin", await ex.run(text, "linkedin", "li"))
    return {"added": len(saved), "notes": ex.notes, "entries": [e.model_dump() for e in await repo.list_context(db, profile)]}


@router.put("/profile/notes")
async def put_notes(body: NotesIn, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    await repo.set_notes(db, profile, body.notes)
    return {"entries": [e.model_dump() for e in await repo.list_context(db, profile)], "notes": profile.notes}


@router.put("/profile/skills")
async def put_skills(body: SkillsIn, profile: Profile = Depends(current)):
    profile.skills = list(dict.fromkeys(s.strip() for s in body.skills if s.strip()))[:200]
    return {"skills": profile.skills}


@router.patch("/profile/context/{entry_id}")
async def patch_entry(entry_id: str, body: EntryIn, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    item = await repo.update_entry(db, profile, entry_id, body.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(404, "No such entry.")
    return item.model_dump()


@router.delete("/profile/context/{entry_id}")
async def remove_entry(entry_id: str, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    if not await repo.delete_entry(db, profile, entry_id):
        raise HTTPException(404, "No such entry.")
    return {"deleted": True}


# --- tailored resumes ---------------------------------------------------------------------------------


class RunIn(BaseModel):
    jd: str = Field(max_length=core.MAX_JD)
    candidates: int = Field(default=1, ge=1, le=3)
    compile: bool = True
    page_limit: int | None = Field(default=None, ge=1, le=4)


class RunRebuildIn(BaseModel):
    ops: list[Op] = Field(max_length=200)
    compile: bool = True


def _evidence(profile: Profile, entries: list[EvidenceItem]) -> list[EvidenceItem]:
    items = list(entries)
    if profile.skills:
        items.append(EvidenceItem(id="skills", source="skill", title="Skills the candidate can defend in an interview", skills=profile.skills))
    return items


@router.post("/runs")
async def create_run(body: RunIn, request: Request, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    """Tailor the saved reference resume to a job, using the stored context; the result is saved to history."""
    core.rate_limit(request, "tailor")
    if not profile.resume_tex.strip():
        raise HTTPException(400, "Add your reference resume first.")
    if not body.jd.strip():
        raise HTTPException(400, "Paste the job description.")
    llm = llm_for(profile)
    await core.ensure_model(llm)
    entries = await repo.list_context(db, profile)
    profile_id, tex, jd = profile.id, profile.resume_tex, body.jd
    inp = TailorInput(
        tex=tex, jd=jd, evidence=_evidence(profile, entries), candidates=body.candidates,
        compile_pdf=body.compile, page_limit=body.page_limit, user=str(profile_id),
    )

    async def save(result: dict) -> None:
        async with engine.sessions()() as s:
            owner = await s.get(Profile, profile_id)
            if owner is not None:
                result["saved_run_id"] = str(await repo.save_run(s, owner, jd, tex, result))
                await s.commit()

    return core.stream_tailoring(inp, llm, ranker=make_ranker(profile_id) if entries else None, on_result=save)


@router.get("/runs")
async def get_runs(profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    return {"runs": await repo.list_runs(db, profile)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    run = await repo.own_run(db, profile, run_id)
    if run is None:
        raise HTTPException(404, "No such resume.")
    return repo.run_payload(run)


@router.post("/runs/{run_id}/rebuild")
async def rebuild_run(run_id: str, body: RunRebuildIn, request: Request, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    core.rate_limit(request, "compile")
    run = await repo.own_run(db, profile, run_id)
    if run is None:
        raise HTTPException(404, "No such resume.")
    try:
        out = await rebuild(run.source_tex, body.ops, JobAnalysis.model_validate(run.result.get("analysis") or {}),
                            _evidence(profile, await repo.list_context(db, profile)), body.compile, run.result.get("page_limit"))
    except UnsafeLatexError as e:
        raise HTTPException(400, str(e)) from None
    await repo.update_run_output(db, run, out["tex"], out["pdf"], out["after"], out["warnings"])
    return out


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, profile: Profile = Depends(current), db: AsyncSession = Depends(db_session)):
    run = await repo.own_run(db, profile, run_id)
    if run is None:
        raise HTTPException(404, "No such resume.")
    await db.delete(run)
    return {"deleted": True}

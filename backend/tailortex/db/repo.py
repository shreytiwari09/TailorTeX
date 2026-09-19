"""Reading and writing profiles, background items (with embeddings), sessions and saved runs."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..evidence.notes import notes_to_evidence
from ..latex.parse import parse_resume
from ..types import EvidenceItem
from .auth import check_password, hash_password, new_token, token_hash
from .embed import embed
from .models import EvidenceRow, Profile, Run, Session

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    pass


# --- sessions and accounts --------------------------------------------------------------


async def profile_for_token(db: AsyncSession, token: str | None) -> Profile | None:
    if not token:
        return None
    row = await db.get(Session, token_hash(token))
    if row is None:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    return await db.get(Profile, row.profile_id)


async def _new_session(db: AsyncSession, profile: Profile) -> str:
    token = new_token()
    db.add(Session(token_hash=token_hash(token), profile_id=profile.id))
    return token


async def create_profile(db: AsyncSession) -> tuple[Profile, str]:
    """A new profile for someone who hasn't signed up yet. The token is their key to it."""
    profile = Profile()
    db.add(profile)
    await db.flush()
    return profile, await _new_session(db, profile)


async def sign_up(db: AsyncSession, profile: Profile, email: str, password: str) -> None:
    """Add an email and password to an existing profile, so it can be opened from any browser."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("That doesn't look like an email address.")
    if len(password) < 8:
        raise AuthError("Use a password of at least 8 characters.")
    if profile.email:
        raise AuthError("This profile already has an account. Sign out to create another.")
    taken = await db.scalar(select(func.count()).select_from(Profile).where(Profile.email == email))
    if taken:
        raise AuthError("An account with that email already exists. Sign in instead.")
    profile.email = email
    profile.password_hash = hash_password(password)


async def sign_in(db: AsyncSession, email: str, password: str) -> tuple[Profile, str]:
    profile = await db.scalar(select(Profile).where(Profile.email == email.strip().lower()))
    if profile is None or not check_password(password, profile.password_hash):
        raise AuthError("Wrong email or password.")
    return profile, await _new_session(db, profile)


async def sign_out(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == token_hash(token)))


# --- the profile --------------------------------------------------------------------------


def _content_hash(item: EvidenceItem) -> str:
    raw = json.dumps([item.source, item.title, item.text, item.skills, item.url], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _embed_text(item: EvidenceItem) -> str:
    return " ".join(p for p in [item.title, item.text, ", ".join(item.skills)] if p)


async def save_profile(
    db: AsyncSession, profile: Profile, *, resume_tex: str | None = None, notes: str | None = None,
    skills: list[str] | None = None, links: dict | None = None, evidence: list[EvidenceItem] | None = None,
) -> dict:
    """Store what changed. Background items are synced by ID; only new or edited ones get new embeddings."""
    if resume_tex is not None:
        profile.resume_tex = resume_tex
        if resume_tex.strip():
            try:
                profile.full_name = parse_resume(resume_tex).name()[:200]
            except Exception:  # an unfinished paste shouldn't block saving
                pass
    if notes is not None:
        profile.notes = notes
    if skills is not None:
        profile.skills = [s.strip() for s in skills if s.strip()][:200]
    if links is not None:
        profile.links = {k: str(v)[:500] for k, v in links.items() if isinstance(v, str)}
    embedded = 0
    if evidence is not None or notes is not None:
        items = list(evidence if evidence is not None else await _stored_items(db, profile, include_notes=False))
        items += notes_to_evidence(profile.notes)
        embedded = await _sync_items(db, profile, items)
    profile.updated_at = datetime.now(timezone.utc)
    return {"embedded": embedded}


async def _sync_items(db: AsyncSession, profile: Profile, items: list[EvidenceItem]) -> int:
    existing = {r.ext_id: r for r in (await db.scalars(select(EvidenceRow).where(EvidenceRow.profile_id == profile.id))).all()}
    wanted: dict[str, EvidenceItem] = {}
    for item in items:
        if item.id and item.id not in wanted:
            wanted[item.id] = item
    for ext_id, row in existing.items():
        if ext_id not in wanted:
            await db.delete(row)
    to_embed: list[tuple[EvidenceRow, EvidenceItem]] = []
    for ext_id, item in wanted.items():
        h = _content_hash(item)
        row = existing.get(ext_id)
        if row is not None and row.content_hash == h and row.embedding is not None:
            continue
        if row is None:
            row = EvidenceRow(profile_id=profile.id, ext_id=ext_id)
            db.add(row)
        row.source, row.title, row.text, row.skills, row.url, row.content_hash = item.source, item.title, item.text, item.skills, item.url, h
        to_embed.append((row, item))
    if to_embed:
        vectors = await embed([_embed_text(item) for _, item in to_embed])
        for (row, _), vec in zip(to_embed, vectors):
            row.embedding = vec
    return len(to_embed)


async def _stored_items(db: AsyncSession, profile: Profile, include_notes: bool = True) -> list[EvidenceItem]:
    rows = (await db.scalars(select(EvidenceRow).where(EvidenceRow.profile_id == profile.id).order_by(EvidenceRow.id))).all()
    out = []
    for r in rows:
        if not include_notes and re.fullmatch(r"n\d+", r.ext_id):
            continue
        out.append(EvidenceItem(id=r.ext_id, source=r.source, title=r.title, text=r.text, skills=r.skills or [], url=r.url))  # type: ignore[arg-type]
    return out


async def load_profile(db: AsyncSession, profile: Profile) -> dict:
    return {
        "full_name": profile.full_name,
        "email": profile.email,
        "has_account": bool(profile.email),
        "resume_tex": profile.resume_tex,
        "notes": profile.notes,
        "skills": profile.skills or [],
        "links": profile.links or {},
        "evidence": [e.model_dump() for e in await _stored_items(db, profile, include_notes=False)],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


async def rank_items(db: AsyncSession, profile: Profile, query: str) -> list[tuple[str, float]]:
    """This profile's background items, closest in meaning to the query first: (ID, similarity 0..1)."""
    [qvec] = await embed([query])
    distance = EvidenceRow.embedding.cosine_distance(qvec)
    rows = (await db.execute(
        select(EvidenceRow.ext_id, distance.label("d"))
        .where(EvidenceRow.profile_id == profile.id, EvidenceRow.embedding.is_not(None))
        .order_by(distance)
    )).all()
    return [(ext_id, round(1 - float(d), 4)) for ext_id, d in rows]


async def delete_profile(db: AsyncSession, profile: Profile) -> None:
    await db.delete(profile)  # sessions, background items and runs go with it (ON DELETE CASCADE)


# --- saved runs -------------------------------------------------------------------------------


async def save_run(db: AsyncSession, profile: Profile, jd: str, result: dict) -> uuid.UUID:
    pdf = base64.b64decode(result["pdf"]) if result.get("pdf") else None
    stored = {k: v for k, v in result.items() if k not in ("pdf", "tex")}
    run = Run(
        profile_id=profile.id, job_title=result.get("analysis", {}).get("title", ""), company=result.get("analysis", {}).get("company"),
        jd=jd, tex=result.get("tex", ""), pdf=pdf, result=stored,
        must_before=result.get("before", {}).get("must_have"), must_after=result.get("after", {}).get("must_have"),
        reward=result.get("reward"), provider=result.get("usage", {}).get("provider"), model=result.get("usage", {}).get("model"),
    )
    db.add(run)
    await db.flush()
    return run.id


async def list_runs(db: AsyncSession, profile: Profile, limit: int = 50) -> list[dict]:
    rows = (await db.scalars(select(Run).where(Run.profile_id == profile.id).order_by(Run.created_at.desc()).limit(limit))).all()
    return [
        {"id": str(r.id), "created_at": r.created_at.isoformat(), "job_title": r.job_title, "company": r.company,
         "must_before": r.must_before, "must_after": r.must_after, "model": r.model, "has_pdf": r.pdf is not None}
        for r in rows
    ]


async def get_run(db: AsyncSession, profile: Profile, run_id: str) -> dict | None:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        return None
    r = await db.get(Run, rid)
    if r is None or r.profile_id != profile.id:
        return None
    return {**r.result, "tex": r.tex, "pdf": base64.b64encode(r.pdf).decode() if r.pdf else None, "saved_run_id": str(r.id), "jd": r.jd}


async def delete_run(db: AsyncSession, profile: Profile, run_id: str) -> bool:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        return False
    r = await db.get(Run, rid)
    if r is None or r.profile_id != profile.id:
        return False
    await db.delete(r)
    return True

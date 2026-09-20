"""Reading and writing accounts, profiles, context entries (with embeddings) and saved runs."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..evidence.notes import notes_to_evidence
from ..latex.parse import parse_resume
from ..types import EvidenceItem
from . import crypto
from .auth import check_password, hash_password, new_token, token_hash
from .embed import embed
from .models import EvidenceRow, Profile, Run, Session

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOTE_ID = re.compile(r"^n\d+$")
DETAIL_FIELDS = ("full_name", "headline", "location", "phone", "public_email")
LINK_KEYS = ("linkedin", "github", "portfolio", "other")


class AuthError(Exception):
    pass


# --- sessions and accounts ------------------------------------------------------------


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


async def sign_up(db: AsyncSession, email: str, password: str, full_name: str = "") -> tuple[Profile, str]:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("That doesn't look like an email address.")
    if len(password) < 8:
        raise AuthError("Use a password of at least 8 characters.")
    if await db.scalar(select(func.count()).select_from(Profile).where(Profile.email == email)):
        raise AuthError("An account with that email already exists. Sign in instead.")
    profile = Profile(email=email, password_hash=hash_password(password), full_name=full_name.strip()[:200], public_email=email)
    db.add(profile)
    await db.flush()
    return profile, await _new_session(db, profile)


DEMO_DAYS = 2


def is_demo(profile: Profile) -> bool:
    return not (profile.email or profile.google_sub or profile.password_hash or profile.firebase_uid)


async def start_demo(db: AsyncSession, sample: dict) -> tuple[Profile, str]:
    """A temporary workspace with the sample resume and background, so the product can be tried without signing up."""
    await purge_demos(db)
    profile = Profile(full_name="Aarav Mehta", headline="Backend engineer", location="Bengaluru, India", resume_tex=sample["tex"], skills=sample["skills"], onboarded=True)
    db.add(profile)
    await db.flush()
    await replace_source(db, profile, "github", [EvidenceItem(**e) for e in sample["evidence"]])
    await set_notes(db, profile, sample["notes"])
    return profile, await _new_session(db, profile)


async def purge_demos(db: AsyncSession) -> int:
    """Demo workspaces (no email, no password, no Google) are deleted after DEMO_DAYS days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEMO_DAYS)
    gone = await db.execute(delete(Profile).where(Profile.email.is_(None), Profile.google_sub.is_(None), Profile.password_hash.is_(None), Profile.firebase_uid.is_(None), Profile.created_at < cutoff))
    return gone.rowcount or 0


async def sign_in(db: AsyncSession, email: str, password: str) -> tuple[Profile, str]:
    profile = await db.scalar(select(Profile).where(Profile.email == email.strip().lower()))
    if profile is None or not check_password(password, profile.password_hash):
        raise AuthError("Wrong email or password." if profile is None or profile.password_hash else "This account uses Google sign-in.")
    return profile, await _new_session(db, profile)


async def sign_in_google(db: AsyncSession, claims: dict) -> tuple[Profile, str, bool]:
    """(profile, session token, created). Links to an existing email account on first Google sign-in."""
    sub, email = str(claims["sub"]), str(claims["email"]).lower()
    profile = await db.scalar(select(Profile).where(Profile.google_sub == sub))
    created = False
    if profile is None:
        profile = await db.scalar(select(Profile).where(Profile.email == email))
        if profile is None:
            profile = Profile(email=email, public_email=email)
            db.add(profile)
            created = True
        profile.google_sub = sub
    if not profile.full_name and claims.get("name"):
        profile.full_name = str(claims["name"])[:200]
    if claims.get("picture"):
        profile.avatar_url = str(claims["picture"])[:1000]
    await db.flush()
    return profile, await _new_session(db, profile), created


async def sign_in_firebase(db: AsyncSession, claims: dict) -> tuple[Profile, str, bool]:
    """(profile, session token, created). Finds the person by Firebase UID, else by verified email, else creates them.

    The token was verified and its email is verified (see db/firebase.py), so linking by email is safe: only
    the owner of that mailbox can get here.
    """
    uid, email = str(claims["sub"]), str(claims["email"]).lower()
    profile = await db.scalar(select(Profile).where(Profile.firebase_uid == uid))
    created = False
    if profile is None:
        profile = await db.scalar(select(Profile).where(Profile.email == email))
        if profile is None:
            profile = Profile(email=email, public_email=email)
            db.add(profile)
            created = True
        profile.firebase_uid = uid
    profile.sign_in_provider = str((claims.get("firebase") or {}).get("sign_in_provider") or "")[:40] or profile.sign_in_provider
    if not profile.full_name and claims.get("name"):
        profile.full_name = str(claims["name"])[:200]
    if claims.get("picture"):
        profile.avatar_url = str(claims["picture"])[:1000]
    await db.flush()
    return profile, await _new_session(db, profile), created


async def sign_out(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == token_hash(token)))


# --- profile ----------------------------------------------------------------------------


def _clean_links(links: dict) -> dict:
    out = {}
    for k in LINK_KEYS:
        v = links.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:500]
    return out


async def update_details(db: AsyncSession, profile: Profile, details: dict) -> None:
    for field in DETAIL_FIELDS:
        if field in details and isinstance(details[field], str):
            setattr(profile, field, details[field].strip()[:320 if field == "public_email" else 200])
    if isinstance(details.get("links"), dict):
        profile.links = _clean_links(details["links"])
    if isinstance(details.get("onboarded"), bool):
        profile.onboarded = details["onboarded"]
    profile.updated_at = datetime.now(timezone.utc)


async def set_resume(db: AsyncSession, profile: Profile, tex: str) -> None:
    profile.resume_tex = tex
    if tex.strip() and not profile.full_name:
        try:
            profile.full_name = parse_resume(tex).name()[:200]
        except Exception:  # an unfinished paste shouldn't block saving
            pass
    profile.updated_at = datetime.now(timezone.utc)


def set_model(profile: Profile, provider: str, model: str | None, key: str | None) -> None:
    profile.model_provider = provider
    profile.model_name = model or None
    if key:
        profile.model_key_enc = crypto.encrypt(key.strip())


def clear_model(profile: Profile) -> None:
    profile.model_provider = profile.model_name = profile.model_key_enc = None


def model_key(profile: Profile) -> str | None:
    return crypto.decrypt(profile.model_key_enc)


def model_info(profile: Profile) -> dict:
    key = model_key(profile)
    return {"provider": profile.model_provider, "model": profile.model_name, "key_saved": bool(key), "key_hint": crypto.hint(key) if key else None}


async def profile_payload(db: AsyncSession, profile: Profile) -> dict:
    counts = dict((await db.execute(
        select(EvidenceRow.source, func.count()).where(EvidenceRow.profile_id == profile.id).group_by(EvidenceRow.source)
    )).all())
    return {
        "id": str(profile.id),
        "account": {"email": profile.email, "google": bool(profile.google_sub) or profile.sign_in_provider == "google.com", "password": bool(profile.password_hash) or profile.sign_in_provider == "password", "avatar_url": profile.avatar_url, "demo": is_demo(profile)},
        "details": {**{f: getattr(profile, f) for f in DETAIL_FIELDS}, "links": profile.links or {}},
        "resume_tex": profile.resume_tex,
        "notes": profile.notes,
        "skills": profile.skills or [],
        "model": model_info(profile),
        "context_counts": counts,
        "onboarded": profile.onboarded,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


async def delete_profile(db: AsyncSession, profile: Profile) -> None:
    await db.delete(profile)  # sessions, context entries and runs go with it (ON DELETE CASCADE)


# --- context entries (the knowledge base) ------------------------------------------------


def _content_hash(item: EvidenceItem) -> str:
    raw = json.dumps([item.source, item.title, item.text, item.skills, item.url], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _embed_text(item: EvidenceItem) -> str:
    return " ".join(p for p in [item.title, item.text, ", ".join(item.skills)] if p)


def _to_item(r: EvidenceRow) -> EvidenceItem:
    return EvidenceItem(id=r.ext_id, source=r.source, title=r.title, text=r.text, skills=r.skills or [], url=r.url)  # type: ignore[arg-type]


async def _write(db: AsyncSession, profile: Profile, items: list[EvidenceItem]) -> int:
    """Insert or update rows by ID, embedding only the new or changed ones."""
    if not items:
        return 0
    ids = [i.id for i in items]
    existing = {r.ext_id: r for r in (await db.scalars(
        select(EvidenceRow).where(EvidenceRow.profile_id == profile.id, EvidenceRow.ext_id.in_(ids))
    )).all()}
    to_embed: list[tuple[EvidenceRow, EvidenceItem]] = []
    for item in items:
        h = _content_hash(item)
        row = existing.get(item.id)
        if row is not None and row.content_hash == h and row.embedding is not None:
            continue
        if row is None:
            row = EvidenceRow(profile_id=profile.id, ext_id=item.id)
            db.add(row)
        row.source, row.title, row.text, row.skills, row.url, row.content_hash = item.source, item.title, item.text, item.skills, item.url, h
        to_embed.append((row, item))
    if to_embed:
        vectors = await embed([_embed_text(item) for _, item in to_embed])
        for (row, _), vec in zip(to_embed, vectors):
            row.embedding = vec
    return len(to_embed)


async def _free_ids(db: AsyncSession, profile: Profile, items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Renumber incoming items whose IDs are taken (li1 -> li4)."""
    taken = set((await db.scalars(select(EvidenceRow.ext_id).where(EvidenceRow.profile_id == profile.id))).all())
    out = []
    for item in items:
        if item.id in taken:
            prefix = re.sub(r"\d+$", "", item.id)
            n = 1
            while f"{prefix}{n}" in taken:
                n += 1
            item = item.model_copy(update={"id": f"{prefix}{n}"})
        taken.add(item.id)
        out.append(item)
    return out


async def replace_source(db: AsyncSession, profile: Profile, source: str, items: list[EvidenceItem], url: str | None = None, exact: bool = False) -> list[EvidenceItem]:
    """A fresh import from one place replaces what was imported from that place before.

    exact=True means these items are the whole set for this source (someone chose them), so anything else
    from that source goes. Otherwise a single repo or page only replaces its own entry.
    """
    q = delete(EvidenceRow).where(EvidenceRow.profile_id == profile.id, EvidenceRow.source == source)
    if source == "portfolio" and url:
        q = q.where(EvidenceRow.url == url)
    if source == "github" and not exact:
        q = q.where(EvidenceRow.ext_id.in_([i.id for i in items]))
    await db.execute(q)
    items = await _free_ids(db, profile, items)
    await _write(db, profile, items)
    profile.updated_at = datetime.now(timezone.utc)
    return items


async def add_source(db: AsyncSession, profile: Profile, source: str, items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Add to what was imported from one place, keeping what's already there."""
    items = await _free_ids(db, profile, items)
    await _write(db, profile, items)
    profile.updated_at = datetime.now(timezone.utc)
    return items


async def set_notes(db: AsyncSession, profile: Profile, notes: str) -> list[EvidenceItem]:
    """Notes are one entry per line (n1, n2, ...)."""
    profile.notes = notes
    items = notes_to_evidence(notes)
    stale = select(EvidenceRow).where(EvidenceRow.profile_id == profile.id, EvidenceRow.source == "fact")
    for row in (await db.scalars(stale)).all():
        if NOTE_ID.match(row.ext_id) and row.ext_id not in {i.id for i in items}:
            await db.delete(row)
    await _write(db, profile, items)
    return items


async def list_context(db: AsyncSession, profile: Profile) -> list[EvidenceItem]:
    rows = (await db.scalars(select(EvidenceRow).where(EvidenceRow.profile_id == profile.id).order_by(EvidenceRow.id))).all()
    return [_to_item(r) for r in rows]


async def update_entry(db: AsyncSession, profile: Profile, ext_id: str, changes: dict) -> EvidenceItem | None:
    row = await db.scalar(select(EvidenceRow).where(EvidenceRow.profile_id == profile.id, EvidenceRow.ext_id == ext_id))
    if row is None:
        return None
    item = _to_item(row).model_copy(update={k: v for k, v in changes.items() if k in ("title", "text", "skills") and v is not None})
    await _write(db, profile, [item])
    return item


async def delete_entry(db: AsyncSession, profile: Profile, ext_id: str) -> bool:
    result = await db.execute(delete(EvidenceRow).where(EvidenceRow.profile_id == profile.id, EvidenceRow.ext_id == ext_id))
    if NOTE_ID.match(ext_id):  # keep the notes text in step with its entries
        lines = [e.text for e in notes_to_evidence(profile.notes) if e.id != ext_id]
        profile.notes = "\n".join(lines)
        await set_notes(db, profile, profile.notes)
    return bool(result.rowcount)


async def rank_items(db: AsyncSession, profile: Profile, query: str) -> list[tuple[str, float]]:
    """This profile's entries, closest in meaning to the query first: (ID, similarity 0..1)."""
    [qvec] = await embed([query])
    distance = EvidenceRow.embedding.cosine_distance(qvec)
    rows = (await db.execute(
        select(EvidenceRow.ext_id, distance.label("d"))
        .where(EvidenceRow.profile_id == profile.id, EvidenceRow.embedding.is_not(None))
        .order_by(distance)
    )).all()
    return [(ext_id, round(1 - float(d), 4)) for ext_id, d in rows]


# --- saved runs ---------------------------------------------------------------------------


async def save_run(db: AsyncSession, profile: Profile, jd: str, source_tex: str, result: dict) -> uuid.UUID:
    pdf = base64.b64decode(result["pdf"]) if result.get("pdf") else None
    analysis = result.get("analysis", {})
    run = Run(
        profile_id=profile.id, job_title=analysis.get("title", ""), company=analysis.get("company"), jd=jd,
        source_tex=result.get("source_tex") or source_tex,  # the file the tailoring really started from
        tex=result.get("tex", ""), pdf=pdf, result={k: v for k, v in result.items() if k not in ("pdf", "tex", "source_tex")},
        must_before=result.get("before", {}).get("must_have"), must_after=result.get("after", {}).get("must_have"),
        reward=result.get("reward"), provider=result.get("usage", {}).get("provider"), model=result.get("usage", {}).get("model"),
    )
    db.add(run)
    await db.flush()
    return run.id


async def update_run_output(db: AsyncSession, run: Run, tex: str, pdf_b64: str | None, after: dict, warnings: list[str],
                            accepted: list[dict] | None = None, ats_after: float | None = None,
                            keywords: list[dict] | None = None, gap_gains: list[dict] | None = None) -> None:
    """Store a rebuilt resume. `accepted` is the operations the person kept, so reopening the run shows
    what they chose rather than every suggestion accepted again."""
    run.tex = tex
    run.pdf = base64.b64decode(pdf_b64) if pdf_b64 else None
    changed = {"after": after, "warnings": warnings}
    if accepted is not None:
        changed["accepted_ops"] = accepted
    if ats_after is not None:
        changed["ats"] = {**(run.result.get("ats") or {}), "after": ats_after}
    if keywords is not None:
        changed["keywords"] = keywords  # so the page reflects the resume as it now stands
    if gap_gains is not None:
        changed["gains"] = {**(run.result.get("gains") or {}), "gaps": gap_gains}
    run.result = {**run.result, **changed}
    run.must_after = after.get("must_have")


async def list_runs(db: AsyncSession, profile: Profile, limit: int = 100) -> list[dict]:
    rows = (await db.scalars(select(Run).where(Run.profile_id == profile.id).order_by(Run.created_at.desc()).limit(limit))).all()
    return [
        {
            "id": str(r.id), "created_at": r.created_at.isoformat(), "job_title": r.job_title, "company": r.company,
            "must_before": r.must_before, "must_after": r.must_after, "health": (r.result.get("after") or {}).get("health"),
            "model": r.model, "has_pdf": r.pdf is not None, "filename": r.result.get("filename"),
        }
        for r in rows
    ]


async def own_run(db: AsyncSession, profile: Profile, run_id: str) -> Run | None:
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        return None
    r = await db.get(Run, rid)
    return r if r is not None and r.profile_id == profile.id else None


def run_payload(r: Run) -> dict:
    return {**r.result, "tex": r.tex, "pdf": base64.b64encode(r.pdf).decode() if r.pdf else None, "saved_run_id": str(r.id), "jd": r.jd}

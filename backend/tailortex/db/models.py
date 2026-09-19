"""Tables: profiles (a person), sessions (logins), evidence items with embeddings, and saved runs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMS = 384


class Base(DeclarativeBase):
    # Read database-filled columns (timestamps) back on insert: async sessions can't lazy-load them later.
    __mapper_args__ = {"eager_defaults": True}


class Profile(Base):
    """One person: account, personal details, reference resume, model settings, notes and confirmed skills.

    Details that rarely change live in plain columns; the searchable background lives in evidence_items.
    """

    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # account
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    sign_in_provider: Mapped[str | None] = mapped_column(String(40))  # google.com, password (email link), ...
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # personal details
    full_name: Mapped[str] = mapped_column(Text, default="")
    headline: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    public_email: Mapped[str] = mapped_column(String(320), default="")
    links: Mapped[dict] = mapped_column(JSONB, default=dict)
    # reference resume and context
    resume_tex: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    # model: the key is encrypted with the server's APP_SECRET and never sent back to the browser
    model_provider: Mapped[str | None] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_key_enc: Mapped[str | None] = mapped_column(Text)
    onboarded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """A signed-in browser. Only a hash of the token is stored."""

    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceRow(Base):
    """One item of someone's background (a repo, a LinkedIn role, a note line) and its embedding."""

    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("profile_id", "ext_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    ext_id: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """A tailored resume: the job, the result and the PDF, so it can be reopened later."""

    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    job_title: Mapped[str] = mapped_column(Text, default="")
    company: Mapped[str | None] = mapped_column(Text)
    jd: Mapped[str] = mapped_column(Text, default="")
    source_tex: Mapped[str] = mapped_column(Text, default="")  # the reference resume the edits apply to (for rebuilds)
    tex: Mapped[str] = mapped_column(Text, default="")
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    must_before: Mapped[float | None] = mapped_column(Float)
    must_after: Mapped[float | None] = mapped_column(Float)
    reward: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(200))

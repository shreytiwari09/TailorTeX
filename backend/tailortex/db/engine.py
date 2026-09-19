"""The database connection. Storage is on when DATABASE_URL is set."""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def enabled() -> bool:
    return database_url() is not None


def sessions() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessions
    if _sessions is None:
        url = database_url()
        if url is None:
            raise RuntimeError("DATABASE_URL isn't set")
        _engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessions


# create_all() only creates missing tables, so columns added later are applied here. Each statement is idempotent.
MIGRATIONS = [
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS firebase_uid VARCHAR(128)",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS sign_in_provider VARCHAR(40)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_profiles_firebase_uid ON profiles (firebase_uid)",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS source_tex TEXT NOT NULL DEFAULT ''",
]


async def init_db() -> None:
    """Create the vector extension and the tables if they don't exist, then apply column migrations."""
    sessions()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in MIGRATIONS:
            await conn.execute(text(statement))


async def dispose() -> None:
    global _engine, _sessions
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessions = None

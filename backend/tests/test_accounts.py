"""Accounts, profile, context and saved resumes, against a real PostgreSQL with pgvector.

Runs when TAILORTEX_TEST_DATABASE_URL points at a database it may wipe, for example
postgresql+asyncpg://tailortex:tailortex@localhost:5432/tailortex_test
"""

import asyncio
import json
import os
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from conftest import MockLLM
from test_pipeline_learn import ANALYSIS, GOOD_PLAN

TEST_DB = os.environ.get("TAILORTEX_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TAILORTEX_TEST_DATABASE_URL to run database tests")

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()


@pytest.fixture
def client(monkeypatch):
    from tailortex.api import main
    from tailortex.db import engine
    from tailortex.db.models import Base

    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("APP_SECRET", "test-secret-for-model-keys")
    monkeypatch.setenv("TAILORTEX_EMBEDDINGS", os.environ.get("TAILORTEX_TEST_EMBEDDINGS", "hashed"))
    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    main._hits.clear()

    async def reset():
        await engine.init_db()
        async with engine._engine.begin() as conn:  # type: ignore[union-attr]
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(reset())
    with TestClient(main.app) as c:
        yield c
    asyncio.run(engine.dispose())


def signup(client, email="asha@example.com", password="correct horse 1"):
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "full_name": ""})
    assert r.status_code == 200, r.text
    return r.json()["profile"]


def db_rows(sql: str, **params):
    """Query the test database directly, on a connection of its own (the app's pool lives on another event loop)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go():
        eng = create_async_engine(TEST_DB)
        try:
            async with eng.connect() as conn:
                return (await conn.execute(text(sql), params)).all()
        finally:
            await eng.dispose()

    return asyncio.run(go())


# --- accounts ------------------------------------------------------------------------------------


def test_signup_signin_signout(client):
    profile = signup(client)
    assert profile["account"]["email"] == "asha@example.com" and profile["account"]["password"]
    assert client.get("/api/auth/me").json()["signed_in"] is True
    assert client.post("/api/auth/signup", json={"email": "ASHA@example.com", "password": "another pass"}).status_code == 400
    client.post("/api/auth/signout")
    assert client.get("/api/auth/me").json()["signed_in"] is False
    assert client.get("/api/profile").status_code == 401
    assert client.post("/api/auth/signin", json={"email": "asha@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/signin", json={"email": "Asha@Example.com", "password": "correct horse 1"}).status_code == 200
    assert client.get("/api/profile").json()["id"] == profile["id"]


def test_google_sign_in_creates_then_reuses_and_links(client, monkeypatch):
    from tailortex.api import account

    async def fake_verify(credential):
        return {"sub": credential, "email": "asha@example.com", "email_verified": True, "name": "Asha Rao", "picture": "https://x/p.png"}

    monkeypatch.setattr(account, "verify", fake_verify)
    email_profile = signup(client)
    client.post("/api/auth/signout")
    r = client.post("/api/auth/google", json={"credential": "google-sub-1"}).json()
    assert r["profile"]["id"] == email_profile["id"] and r["created"] is False  # linked to the email account
    assert r["profile"]["account"]["google"] is True and r["profile"]["details"]["full_name"] == "Asha Rao"
    client.post("/api/auth/signout")
    again = client.post("/api/auth/google", json={"credential": "google-sub-1"}).json()
    assert again["profile"]["id"] == email_profile["id"]


def _google_token(key, **claims):
    base = {"iss": "https://accounts.google.com", "aud": "client-123", "sub": "42", "email": "a@b.co", "email_verified": True,
            "exp": int(time.time()) + 600, "iat": int(time.time())}
    return jwt.encode({**base, **claims}, key, algorithm="RS256", headers={"kid": "k1"})


def test_google_token_verification(monkeypatch):
    from tailortex.db import google

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, _token):
            return type("K", (), {"key": private.public_key()})()

    monkeypatch.setattr(google, "_keys", lambda: Keys())
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    assert google.verify_sync(_google_token(private))["sub"] == "42"
    for bad in (
        _google_token(private, aud="someone-else"),
        _google_token(private, exp=int(time.time()) - 10),
        _google_token(private, iss="https://evil.example"),
        _google_token(private, email_verified=False),
        _google_token(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    ):
        with pytest.raises(google.GoogleAuthError):
            google.verify_sync(bad)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    with pytest.raises(google.GoogleAuthError, match="isn't set up"):
        google.verify_sync(_google_token(private))


# --- profile ----------------------------------------------------------------------------------------


def test_details_resume_and_encrypted_model_key(client, monkeypatch):
    from tailortex.llm.client import LLMClient, ModelInfo

    signup(client)
    r = client.put("/api/profile", json={"headline": "Backend engineer", "location": "Bengaluru",
                                         "links": {"github": "github.com/asha", "evil": "x"}, "onboarded": True}).json()
    assert r["details"]["headline"] == "Backend engineer" and r["details"]["links"] == {"github": "github.com/asha"} and r["onboarded"]
    out = client.put("/api/profile/resume", json={"tex": JAKE}).json()
    assert out["outline"]["stats"]["editable"] > 5
    assert client.get("/api/profile").json()["details"]["full_name"] == "Aarav Mehta"  # filled from the resume header

    async def fake_models(self):
        return [ModelInfo("gemini-2.5-flash", "Gemini 2.5 Flash"), ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro")]

    monkeypatch.setattr(LLMClient, "list_models", fake_models)
    key = "AIzaSyTESTKEY-1234567890abcdefWXYZ"
    r = client.put("/api/profile/model", json={"key": key})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == {"provider": "google", "model": "gemini-2.5-flash", "key_saved": True, "key_hint": "…WXYZ"}
    everything = json.dumps(client.get("/api/profile").json())
    assert key not in everything
    [(stored,)] = db_rows("select model_key_enc from profiles")
    assert stored and key not in stored
    # changing only the model keeps the saved key
    r = client.put("/api/profile/model", json={"model": "gemini-2.5-pro"}).json()
    assert r["model"]["model"] == "gemini-2.5-pro" and r["model"]["key_saved"]
    assert client.delete("/api/profile/model").json()["model"]["key_saved"] is False


# --- context ------------------------------------------------------------------------------------------


def test_context_links_linkedin_notes_edit_delete(client, monkeypatch):
    from tailortex.api import account
    from tailortex.types import EvidenceItem

    signup(client)

    async def fake_best(user, n=6):
        return [EvidenceItem(id="gh-ledgerly", source="github", title="ledgerly", text="Bookkeeping API in Go on Kubernetes.", skills=["Go", "Kubernetes"])]

    async def fake_fetch(url):
        return url, "<html><body><h1>Projects</h1><p>ChatRelay: a real-time chat server with WebSockets and Redis, used by 300 students.</p></body></html>"

    monkeypatch.setattr(account, "best_repos", fake_best)
    monkeypatch.setattr(account, "fetch_page", fake_fetch)
    r = client.post("/api/profile/context/links", json={"github": "asha", "portfolio": "asha.dev"}).json()
    assert [x["added"] for x in r["results"]] == [1, 1] and all(x["error"] is None for x in r["results"])
    assert client.get("/api/profile").json()["details"]["links"] == {"github": "asha", "portfolio": "asha.dev"}

    li = client.post("/api/profile/context/linkedin", json={"text": "Software Engineer at Finch Payments.\n\nBuilt Kafka consumers in Python for settlement events. Migrated 12 services to Kubernetes."})
    assert li.status_code == 200 and li.json()["added"] >= 1

    r = client.put("/api/profile/notes", json={"notes": "Won 2nd place at DevHacks 2025\nLed the robotics club"}).json()
    ids = {e["id"] for e in r["entries"]}
    assert {"gh-ledgerly", "n1", "n2"} <= ids and any(i.startswith("pf") for i in ids) and any(i.startswith("li") for i in ids)
    assert all(v for (v,) in db_rows("select embedding is not null from evidence_items"))

    [(before,)] = db_rows("select content_hash from evidence_items where ext_id='gh-ledgerly'")
    client.patch("/api/profile/context/gh-ledgerly", json={"text": "Bookkeeping API in Go, deployed on Kubernetes with Helm."})
    [(after,)] = db_rows("select content_hash from evidence_items where ext_id='gh-ledgerly'")
    assert before != after

    assert client.delete("/api/profile/context/n1").json()["deleted"]
    ctx = client.get("/api/profile/context").json()
    assert ctx["notes"] == "Led the robotics club" and [e["id"] for e in ctx["entries"] if e["id"].startswith("n")] == ["n1"]
    assert client.delete("/api/profile/context/nope").status_code == 404


# --- saved resumes -----------------------------------------------------------------------------------


def _stream(client, path, body):
    events = []
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_runs_use_stored_context_are_saved_and_private(client, monkeypatch):
    from tailortex.api import account

    signup(client)
    client.put("/api/profile/resume", json={"tex": JAKE})
    client.put("/api/profile/notes", json={"notes": "Deployed the Ledgerly API on Kubernetes"})
    llm = MockLLM(ANALYSIS, [GOOD_PLAN])
    monkeypatch.setattr(account, "llm_for", lambda profile: llm)
    events = _stream(client, "/api/runs", {"jd": "Backend role: Python, Kubernetes, REST APIs", "compile": False})
    result = events[-1]
    assert result["type"] == "result", result
    assert result["saved_run_id"] and isinstance(result["recommendations"], list)
    assert any(e.get("stage") == "background" for e in events)  # context was ranked for the job
    # the model saw the stored note as evidence
    assert any("Deployed the Ledgerly API on Kubernetes" in user for _system, user in llm.prompts)

    runs = client.get("/api/runs").json()["runs"]
    assert len(runs) == 1 and runs[0]["id"] == result["saved_run_id"] and runs[0]["job_title"] == ANALYSIS["title"]
    saved = client.get(f"/api/runs/{result['saved_run_id']}").json()
    assert saved["tex"] == result["tex"] and saved["jd"].startswith("Backend role")

    assert not any(o["op"] == "add" for o in saved["ops"])  # the plan's add cites evidence this person doesn't have: blocked
    kept = saved["ops"][1:]  # revert the first change
    rebuilt = client.post(f"/api/runs/{result['saved_run_id']}/rebuild", json={"ops": kept, "compile": False}).json()
    assert client.get(f"/api/runs/{result['saved_run_id']}").json()["tex"] == rebuilt["tex"] != result["tex"]

    # another person can't see or touch it
    client.post("/api/auth/signout")
    signup(client, "ravi@example.com")
    assert client.get("/api/runs").json()["runs"] == []
    assert client.get(f"/api/runs/{result['saved_run_id']}").status_code == 404
    assert client.delete(f"/api/runs/{result['saved_run_id']}").status_code == 404


def test_delete_account_removes_everything(client):
    signup(client)
    client.put("/api/profile/notes", json={"notes": "One\nTwo"})
    assert db_rows("select count(*) from evidence_items")[0][0] == 2
    assert client.delete("/api/profile").json()["deleted"]
    assert db_rows("select count(*) from profiles")[0][0] == 0
    assert db_rows("select count(*) from evidence_items")[0][0] == 0
    assert db_rows("select count(*) from sessions")[0][0] == 0
    assert client.get("/api/auth/me").json()["signed_in"] is False


@pytest.mark.skipif(os.environ.get("TAILORTEX_TEST_EMBEDDINGS") != "model", reason="needs the local embedding model")
def test_ranking_finds_by_meaning(client):
    from tailortex.db import engine, repo
    from tailortex.db.models import Profile

    signup(client)
    client.put("/api/profile/notes", json={"notes": "Built Kafka consumers for settlement events\nBaked sourdough for the office\nPainted a mural"})

    async def go():
        await engine.dispose()  # fresh pool on this event loop
        try:
            async with engine.sessions()() as s:
                profile = (await s.execute(__import__("sqlalchemy").select(Profile))).scalar_one()
                return await repo.rank_items(s, profile, "event streaming pipelines engineer")
        finally:
            await engine.dispose()

    ranked = asyncio.run(go())
    assert ranked[0][0] == "n1", ranked

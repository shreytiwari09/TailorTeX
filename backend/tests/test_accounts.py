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
needs_db = pytest.mark.skipif(not TEST_DB, reason="set TAILORTEX_TEST_DATABASE_URL to run database tests")

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
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "")  # the built-in sign-in, whatever .env says
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


def db_exec(sql: str):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go():
        eng = create_async_engine(TEST_DB)
        try:
            async with eng.begin() as conn:
                await conn.execute(text(sql))
        finally:
            await eng.dispose()

    asyncio.run(go())


# --- accounts ------------------------------------------------------------------------------------


@needs_db
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


@needs_db
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


@needs_db
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


@needs_db
def test_context_links_linkedin_notes_edit_delete(client, monkeypatch):
    from tailortex.api import account
    from tailortex.types import EvidenceItem

    signup(client)

    async def fake_best(user):
        return [EvidenceItem(id="gh-ledgerly", source="github", title="ledgerly", text="Bookkeeping API in Go on Kubernetes.", skills=["Go", "Kubernetes"])], []

    async def fake_fetch(url):
        return url, "<html><body><h1>Projects</h1><p>ChatRelay: a real-time chat server with WebSockets and Redis, used by 300 students.</p></body></html>"

    monkeypatch.setattr(account, "all_or_choice", fake_best)
    monkeypatch.setattr(account, "fetch_page", fake_fetch)
    r = client.post("/api/profile/context/links", json={"github": "asha", "portfolio": "asha.dev"}).json()
    assert [x["added"] for x in r["results"]] == [1, 1] and all(x["error"] is None for x in r["results"])
    assert client.get("/api/profile").json()["details"]["links"] == {"github": "asha", "portfolio": "asha.dev"}

    li = client.post("/api/profile/context/linkedin", json={"text": "Software Engineer at Finch Payments.\n\nBuilt Kafka consumers in Python for settlement events. Migrated 12 services to Kubernetes."})
    assert li.status_code == 200 and li.json()["added"] >= 1

    r = client.put("/api/profile/notes", json={"notes": "Won 2nd place at DevHacks 2025\n\nLed the robotics club"}).json()
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


@needs_db
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


@needs_db
def test_delete_account_removes_everything(client):
    signup(client)
    client.put("/api/profile/notes", json={"notes": "One\n\nTwo"})
    assert db_rows("select count(*) from evidence_items")[0][0] == 2
    assert client.delete("/api/profile").json()["deleted"]
    assert db_rows("select count(*) from profiles")[0][0] == 0
    assert db_rows("select count(*) from evidence_items")[0][0] == 0
    assert db_rows("select count(*) from sessions")[0][0] == 0
    assert client.get("/api/auth/me").json()["signed_in"] is False


@pytest.mark.skipif(os.environ.get("TAILORTEX_TEST_EMBEDDINGS") != "model", reason="needs the local embedding model")
@needs_db
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


def test_secret_is_generated_and_kept_when_app_secret_is_unset(monkeypatch, tmp_path):
    from tailortex.db import crypto

    monkeypatch.delenv("APP_SECRET", raising=False)
    monkeypatch.setenv("TAILORTEX_DATA_DIR", str(tmp_path))
    token = crypto.encrypt("sk-secret-key-value")
    file = tmp_path / "app_secret"
    assert file.exists() and oct(file.stat().st_mode)[-3:] == "600"
    assert crypto.decrypt(token) == "sk-secret-key-value"        # the same secret is reused
    monkeypatch.setenv("APP_SECRET", "a-different-secret-that-is-long-enough")
    assert crypto.decrypt(token) is None                          # another secret can't read it
    monkeypatch.setenv("APP_SECRET", "short")
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        crypto.encrypt("x")


# --- demo workspace ---------------------------------------------------------------------------------


@needs_db
def test_demo_workspace_is_prefilled_private_and_expires(client):
    r = client.post("/api/auth/demo")
    assert r.status_code == 200, r.text
    body = r.json()
    profile = body["profile"]
    assert profile["account"]["demo"] is True and profile["account"]["email"] is None
    assert profile["onboarded"] and "\\documentclass" in profile["resume_tex"] and len(body["jd"].split()) > 30
    entries = client.get("/api/profile/context").json()["entries"]
    assert {e["source"] for e in entries} >= {"github", "fact"}
    assert client.get("/api/auth/me").json()["profile"]["account"]["demo"] is True

    old_cookie = client.cookies.get("tt_session")

    # a real account is not a demo, and can't see the demo workspace
    client.post("/api/auth/signout")
    signup(client, "real@example.com", "long enough pw")
    assert client.get("/api/auth/me").json()["profile"]["account"]["demo"] is False
    assert client.get("/api/profile/context").json()["entries"] == []

    # a demo older than two days is deleted the next time a demo is started; accounts with an email are kept
    db_exec("update profiles set created_at = now() - interval '3 days'")
    client.post("/api/auth/signout")
    assert client.post("/api/auth/demo").status_code == 200
    assert db_rows("select count(*) from profiles")[0][0] == 2  # the real account and the new demo
    client.cookies.set("tt_session", old_cookie)
    assert client.get("/api/auth/me").json()["signed_in"] is False


# --- Firebase sign-in --------------------------------------------------------------------------------

FIREBASE_PROJECT = "tailortex-test"


def _firebase_token(key, **claims):
    now = int(time.time())
    base = {"iss": f"https://securetoken.google.com/{FIREBASE_PROJECT}", "aud": FIREBASE_PROJECT, "sub": "uid-1", "email": "asha@example.com",
            "email_verified": True, "iat": now, "exp": now + 600, "firebase": {"sign_in_provider": "password"}}
    return jwt.encode({**base, **claims}, key, algorithm="RS256", headers={"kid": "k1"})


def _fake_firebase_keys(monkeypatch, private):
    from tailortex.db import firebase

    class Keys:
        def get_signing_key_from_jwt(self, _token):
            return type("K", (), {"key": private.public_key()})()

    monkeypatch.setattr(firebase, "_keys", lambda: Keys())
    monkeypatch.setenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT)


def test_firebase_token_verification(monkeypatch):
    from tailortex.db import firebase

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _fake_firebase_keys(monkeypatch, private)
    assert firebase.verify_sync(_firebase_token(private))["sub"] == "uid-1"
    now = int(time.time())
    for bad in (
        _firebase_token(private, aud="another-project"),
        _firebase_token(private, iss="https://securetoken.google.com/another-project"),
        _firebase_token(private, exp=now - 10),
        _firebase_token(private, email_verified=False),
        _firebase_token(private, email=None),
        _firebase_token(private, sub=""),
        _firebase_token(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        "not-a-token",
    ):
        with pytest.raises(firebase.FirebaseAuthError):
            firebase.verify_sync(bad)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "")
    with pytest.raises(firebase.FirebaseAuthError, match="isn't set up"):
        firebase.verify_sync(_firebase_token(private))


def test_firebase_web_config(monkeypatch):
    from tailortex.db import firebase

    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN", "FIREBASE_APP_ID"):
        monkeypatch.setenv(name, "")
    assert firebase.web_config() is None
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-proj")
    assert firebase.web_config() is None  # needs the API key too
    monkeypatch.setenv("FIREBASE_API_KEY", "AIza-public")
    assert firebase.web_config() == {"apiKey": "AIza-public", "authDomain": "demo-proj.firebaseapp.com", "projectId": "demo-proj", "appId": None}


@needs_db
def test_firebase_sign_in_creates_reuses_and_links(client, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _fake_firebase_keys(monkeypatch, private)
    monkeypatch.setenv("FIREBASE_API_KEY", "AIza-public")
    assert client.get("/api/auth/config").json()["firebase"]["projectId"] == FIREBASE_PROJECT

    first = client.post("/api/auth/firebase", json={"id_token": _firebase_token(private, name="Asha Rao", picture="https://x.test/a.png")})
    assert first.status_code == 200 and first.json()["created"] is True
    assert "tt_session" in first.cookies and "httponly" in first.headers["set-cookie"].lower()
    profile = first.json()["profile"]
    assert profile["account"]["email"] == "asha@example.com" and profile["details"]["full_name"] == "Asha Rao"
    assert client.get("/api/auth/me").json()["signed_in"] is True

    # the same Firebase user again is the same profile, even if the email changed
    client.post("/api/auth/signout")
    again = client.post("/api/auth/firebase", json={"id_token": _firebase_token(private, email="asha.new@example.com")}).json()
    assert again["created"] is False and again["profile"]["id"] == profile["id"]

    # someone new with an unverified email is turned away, and nothing is created
    client.post("/api/auth/signout")
    rejected = client.post("/api/auth/firebase", json={"id_token": _firebase_token(private, sub="uid-2", email="ravi@example.com", email_verified=False)})
    assert rejected.status_code == 401 and "Verify your email" in rejected.json()["detail"]
    assert db_rows("select count(*) from profiles where email = 'ravi@example.com'")[0][0] == 0
    assert client.get("/api/auth/me").json()["signed_in"] is False

    # with Firebase on, the built-in sign-up and sign-in are closed
    for path in ("signup", "signin"):
        assert client.post(f"/api/auth/{path}", json={"email": "x@example.com", "password": "long enough pw"}).status_code == 400
    assert client.post("/api/auth/google", json={"credential": "x"}).status_code == 400


@needs_db
def test_firebase_links_to_an_existing_account_by_verified_email(client, monkeypatch):
    existing = signup(client, "maya@example.com")  # made with the built-in sign-in before Firebase was switched on
    client.post("/api/auth/signout")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _fake_firebase_keys(monkeypatch, private)
    r = client.post("/api/auth/firebase", json={"id_token": _firebase_token(private, sub="uid-maya", email="Maya@Example.com", firebase={"sign_in_provider": "google.com"})})
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["profile"]["id"] == existing["id"]
    assert r.json()["profile"]["account"]["google"] is True
    assert db_rows("select firebase_uid from profiles where email = 'maya@example.com'")[0][0] == "uid-maya"


def test_signing_key_set_is_cached_refetches_rarely_and_reports_network_errors(monkeypatch):
    import httpx
    from jwt.algorithms import RSAAlgorithm

    from tailortex.db import jwks
    from tailortex.db.jwks import KeySet

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {**RSAAlgorithm.to_jwk(private.public_key(), as_dict=True), "kid": "k1", "alg": "RS256", "use": "sig"}
    calls = []

    def fake_get(url, **_kw):
        calls.append(url)
        if len(calls) == 99:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"keys": [jwk]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(jwks.httpx, "get", fake_get)
    keys = KeySet("https://example.test/jwks")
    token = _firebase_token(private)  # kid k1
    assert keys.get_signing_key_from_jwt(token).key.public_numbers() == private.public_key().public_numbers()
    keys.get_signing_key_from_jwt(token)
    assert len(calls) == 1  # cached

    other = jwt.encode({"a": 1}, private, algorithm="RS256", headers={"kid": "unknown"})
    for _ in range(3):
        with pytest.raises(jwt.PyJWKClientError):
            keys.get_signing_key_from_jwt(other)
    assert len(calls) == 1  # junk key IDs don't make us refetch every time

    fresh = KeySet("https://example.test/jwks")
    calls.extend([None] * (98 - len(calls)))  # the next fetch is the failing one
    with pytest.raises(jwt.PyJWKClientError, match="couldn't fetch"):
        fresh.get_signing_key_from_jwt(token)


# --- choosing which repositories speak for you --------------------------------------------------------


@needs_db
def test_many_repos_are_offered_for_choosing_instead_of_picking_for_you(client, monkeypatch):
    from tailortex.api import account
    from tailortex.evidence import github
    from tailortex.types import EvidenceItem

    signup(client)
    repos = [{"name": f"repo{i}", "description": f"Project {i}", "language": "Python", "topics": [], "stars": i,
              "fork": False, "url": f"https://github.com/asha/repo{i}", "pushed_at": f"2026-01-{i:02d}T00:00:00Z"} for i in range(1, 13)]

    async def fake_list(user):
        return repos

    imported = []

    async def fake_import(user, names, known=None):
        imported.append(list(names))
        return [EvidenceItem(id=f"gh-{n}", source="github", title=n, text=f"{n} does things.", skills=["Python"]) for n in names]

    monkeypatch.setattr(github, "list_repos", fake_list)
    monkeypatch.setattr(account.core, "import_repos", fake_import)

    # 12 repos is more than the app will pick for you: it hands back the whole list and imports nothing
    r = client.post("/api/profile/context/links", json={"github": "asha"}).json()["results"][0]
    assert r["error"] is None and r["added"] == 0
    assert r["choose"]["user"] == "asha" and len(r["choose"]["repos"]) == 12
    assert [x["name"] for x in r["choose"]["repos"]][:3] == ["repo12", "repo11", "repo10"]  # most stars first
    assert imported == [] and client.get("/api/profile/context").json()["entries"] == []

    # the person picks, and only those are read
    picked = ["repo12", "repo3"]
    out = client.post("/api/profile/context/github", json={"user": "asha", "repos": picked}).json()
    assert out["added"] == 2 and imported == [picked]
    assert {e["id"] for e in out["entries"]} == {"gh-repo12", "gh-repo3"}
    assert client.get("/api/profile").json()["details"]["links"]["github"] == "asha"  # the link they typed is kept

    # picking again replaces the earlier import rather than piling up
    client.post("/api/profile/context/github", json={"user": "asha", "repos": ["repo1"]})
    assert {e["id"] for e in client.get("/api/profile/context").json()["entries"]} == {"gh-repo1"}
    assert client.post("/api/profile/context/github", json={"user": "asha", "repos": []}).status_code == 400


@needs_db
def test_a_handful_of_repos_are_all_imported_without_asking(client, monkeypatch):
    from tailortex.api import account
    from tailortex.evidence import github
    from tailortex.types import EvidenceItem

    signup(client)
    repos = [{"name": f"repo{i}", "description": "", "language": None, "topics": [], "stars": 0, "fork": False,
              "url": f"https://github.com/asha/repo{i}", "pushed_at": "2026-01-01T00:00:00Z"} for i in range(1, 4)]
    repos.append({**repos[0], "name": "someone-elses", "fork": True})

    async def fake_list(user):
        return repos

    async def fake_import(user, names, known=None):
        return [EvidenceItem(id=f"gh-{n}", source="github", title=n, text=f"{n}.", skills=[]) for n in names]

    monkeypatch.setattr(github, "list_repos", fake_list)
    monkeypatch.setattr(account.core, "import_repos", fake_import)
    r = client.post("/api/profile/context/links", json={"github": "asha"}).json()["results"][0]
    assert r["added"] == 3 and "choose" not in r  # forks aren't your work


# --- telling us about skills the resume doesn't show -----------------------------------------------


def _saved_run(client, monkeypatch):
    """Sign up, store the sample resume and a run for a job that wants PyTorch."""
    from tailortex.api import account

    signup(client)
    client.put("/api/profile/resume", json={"tex": JAKE})
    analysis = {**ANALYSIS, "title": "ML Engineer",
                "must_have": [{"term": "PyTorch", "weight": 3}, {"term": "Python", "weight": 3}, {"term": "TensorFlow", "weight": 2}]}
    llm = MockLLM(analysis, [{"ops": []}])
    monkeypatch.setattr(account, "llm_for", lambda profile: llm)
    events = _stream(client, "/api/runs", {"jd": "ML Engineer: PyTorch, Python, TensorFlow", "compile": False})
    assert events[-1]["type"] == "result", events[-1]
    return events[-1]["saved_run_id"], llm


PYTORCH = "At Finch Payments I trained a PyTorch model that flags fraudulent transfers and cut manual review time by 30%"
PYTORCH_BULLET = {"ops": [{"op": "add", "target": "s1.e0", "after": "s1.e0.b1", "evidence": ["ans1"], "reason": "the job asks for PyTorch",
                           "text": "Trained a PyTorch model that flags fraudulent transfers, cutting manual review time by 30%"}], "followups": []}


@needs_db
def test_an_answer_is_stored_as_context_drafted_and_applied_through_rebuild(client, monkeypatch):
    run_id, llm = _saved_run(client, monkeypatch)
    llm.plans = [PYTORCH_BULLET]
    llm.plan_calls = 0

    r = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{"term": "PyTorch", "text": PYTORCH, "target": "s1.e0"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["ops"]) == 1 and body["ops"][0]["evidence"] == ["ans1"] and body["ops"][0]["source"] == "model"
    assert not body["blocked"] and body["changes"][0]["gain"] > 0

    # it was kept as permanent context, so every later tailoring can use it
    entries = client.get("/api/profile/context").json()["entries"]
    stored = next(e for e in entries if e["id"] == "ans1")
    assert stored["source"] == "fact" and stored["text"] == PYTORCH and "PyTorch" in stored["skills"]

    # nothing changed in the saved resume yet: the draft has to be accepted first
    assert "PyTorch model" not in client.get(f"/api/runs/{run_id}").json()["tex"]

    # accepting = the ordinary rebuild, and it validates because the answer is now evidence
    done = client.post(f"/api/runs/{run_id}/rebuild", json={"ops": body["ops"], "compile": False}).json()
    assert "PyTorch model that flags fraudulent transfers" in done["tex"] and not done["warnings"]
    saved = client.get(f"/api/runs/{run_id}").json()
    assert "PyTorch model" in saved["tex"] and saved["accepted_ops"][0]["evidence"] == ["ans1"]  # reopening remembers the choice
    assert saved["ats"]["after"] == done["ats"]

    # an answer the person has just given must stop being offered as a missing skill
    assert next(k for k in saved["keywords"] if k["term"] == "PyTorch")["after"] == "context"
    assert "PyTorch" not in [g["term"] for g in saved["gains"]["gaps"]]
    assert "TensorFlow" in [g["term"] for g in saved["gains"]["gaps"]]  # the ones they didn't answer still are


@needs_db
def test_a_second_round_gets_the_next_number_and_a_notes_save_leaves_answers_alone(client, monkeypatch):
    run_id, llm = _saved_run(client, monkeypatch)
    llm.plans = [PYTORCH_BULLET]
    client.post(f"/api/runs/{run_id}/answers", json={"answers": [{"term": "PyTorch", "text": PYTORCH}]})

    second = {"ops": [{"op": "add", "target": "s1.e1", "after": "s1.e1.b0", "evidence": ["ans2"], "reason": "x",
                       "text": "Built a TensorFlow classifier for support tickets that routed 2,000 tickets a week"}], "followups": []}
    llm.plans, llm.plan_calls = [second], 0
    r = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{
        "term": "TensorFlow", "text": "For the analytics team I built a TensorFlow classifier for support tickets that routed 2,000 tickets a week"}]})
    assert r.status_code == 200 and r.json()["evidence"][0]["id"] == "ans2"

    # a notes save only touches n1, n2, ... so the answers survive it
    client.put("/api/profile/notes", json={"notes": "Led the robotics club"})
    ids = {e["id"] for e in client.get("/api/profile/context").json()["entries"]}
    assert {"ans1", "ans2", "n1"} <= ids


@needs_db
def test_a_one_line_claim_is_turned_away_before_a_model_is_called(client, monkeypatch):
    run_id, llm = _saved_run(client, monkeypatch)
    calls = llm.plan_calls
    r = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{"term": "PyTorch", "text": "I know it"}]})
    assert r.status_code == 400 and "a little more about PyTorch" in r.json()["detail"]
    assert llm.plan_calls == calls  # no model call was spent


@needs_db
def test_nobody_else_can_answer_for_your_run(client, monkeypatch):
    run_id, llm = _saved_run(client, monkeypatch)
    client.post("/api/auth/signout")
    signup(client, "ravi@example.com")
    r = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{"term": "PyTorch", "text": PYTORCH}]})
    assert r.status_code == 404
    assert not [e for e in client.get("/api/profile/context").json()["entries"] if e["id"].startswith("ans")]


@needs_db
def test_a_separate_project_comes_back_as_latex_and_the_answer_is_still_kept(client, monkeypatch):
    run_id, llm = _saved_run(client, monkeypatch)
    llm.plans = [{"ops": [], "followups": [], "projects": [{"answer": "ans1", "bullets": [
        "Trained a **PyTorch** model in **Python** that flags fraudulent card transfers",
        "Cut manual review time by **30%** by ranking the transfers most likely to be fraud"]}]}]
    llm.plan_calls = 0
    text = "For a course project I trained a PyTorch model in Python that flags fraudulent card transfers and cut manual review time by 30%"
    r = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{
        "term": "PyTorch", "text": text, "project": {"name": "Fraud Detector", "dates": "Jan 2026 - Apr 2026", "tech": ["PyTorch", "Python"]}}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ops"] == [] and len(body["projects"]) == 1
    p = body["projects"][0]
    assert "\\resumeProjectHeading" in p["latex"] and "Fraud Detector" in p["tex_with_project"] and p["ats_after"] > p["ats_before"]
    assert next(e for e in client.get("/api/profile/context").json()["entries"] if e["id"] == "ans1")["title"] == "Project: Fraud Detector"
    # nothing was changed in the saved resume: pasting it into Overleaf is the person's step
    assert "Fraud Detector" not in client.get(f"/api/runs/{run_id}").json()["tex"]

    # a project with no name is turned away before a model is called
    calls = llm.plan_calls
    bad = client.post(f"/api/runs/{run_id}/answers", json={"answers": [{"term": "PyTorch", "text": text, "project": {"name": " ", "tech": []}}]})
    assert bad.status_code in (400, 422) and llm.plan_calls == calls


@needs_db
def test_the_dashboard_and_the_result_page_show_the_same_ats_score(client, monkeypatch):
    """There used to be three numbers called ATS: keyword share, PDF readability and the combined score."""
    run_id, _ = _saved_run(client, monkeypatch)
    listed = client.get("/api/runs").json()["runs"][0]
    saved = client.get(f"/api/runs/{run_id}").json()
    assert listed["ats_before"] == saved["ats"]["before"] and listed["ats_after"] == saved["ats"]["after"]
    assert 0 < listed["ats_after"] < 1  # a composite, not the must-have share (which is its own field)
    assert listed["ats_after"] != listed["must_after"]


@needs_db
def test_a_run_saved_before_the_combined_score_still_gets_one(client, monkeypatch):
    """Old runs had no `ats`; the list derives it from their stored measurements, and an update completes it."""
    run_id, _ = _saved_run(client, monkeypatch)
    db_exec("update runs set result = result - 'ats'")  # as if it were saved before the combined score existed
    listed = client.get("/api/runs").json()["runs"][0]
    assert listed["ats_before"] is not None and listed["ats_after"] is not None
    done = client.post(f"/api/runs/{run_id}/rebuild", json={"ops": [], "compile": False}).json()
    saved = client.get(f"/api/runs/{run_id}").json()
    assert saved["ats"]["before"] is not None and saved["ats"]["after"] == done["ats"]  # complete, so the page never shows "NaN%"

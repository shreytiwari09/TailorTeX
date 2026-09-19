import json

import pytest
from fastapi.testclient import TestClient

from conftest import MockLLM
from test_pipeline_learn import ANALYSIS, GOOD_PLAN
from tailortex.api import main
from tailortex.evidence.github import clean_readme
from tailortex.compile.compile import tex_available


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    main._hits.clear()
    return TestClient(main.app)


def test_health_config_detect(client):
    assert client.get("/health").json()["ok"] is True
    cfg = client.get("/api/config").json()
    assert cfg["server_key"] is False and len(cfg["providers"]) == 7
    assert client.post("/api/providers/detect", json={"key": "gsk_abc"}).json()["provider"] == "groq"


def test_sample_and_parse_and_lint_fix(client):
    s = client.get("/api/sample").json()
    assert "\\resumeItem" in s["tex"] and "Kafka" in s["jd"] and s["evidence"]
    o = client.post("/api/parse", json={"tex": s["tex"]}).json()
    assert o["profile"] == "jake" and o["stats"]["editable"] > 5
    assert not [i for i in o["lint"] if i["severity"] == "warn"]
    broken = s["tex"].replace("\\pdfgentounicode=1", "")
    o = client.post("/api/parse", json={"tex": broken}).json()
    assert any(i["id"] == "glyphtounicode" for i in o["lint"])
    fixed = client.post("/api/lint/fix", json={"tex": broken, "fix": "glyphtounicode"}).json()
    assert "\\pdfgentounicode=1" in fixed["tex"]


def test_models_needs_key(client):
    r = client.post("/api/models", json={})
    assert r.status_code == 400 and "key" in r.json()["detail"].lower()


@pytest.mark.skipif(not tex_available(), reason="TeX Live not installed")
def test_compile_endpoint(client):
    s = client.get("/api/sample").json()
    r = client.post("/api/compile", json={"tex": s["tex"]}).json()
    assert r["ok"] and r["pages"] == 1 and r["pdf"]
    bad = client.post("/api/compile", json={"tex": "\\documentclass{article}\\begin{document}\\input{/etc/passwd}\\end{document}"})
    assert bad.status_code == 400


def test_tailor_stream_rebuild_feedback(client, monkeypatch):
    monkeypatch.setattr(main, "make_llm", lambda req: MockLLM(ANALYSIS, [GOOD_PLAN]))
    s = client.get("/api/sample").json()
    body = {"tex": s["tex"], "jd": s["jd"], "evidence": s["evidence"], "skills": s["skills"], "compile": False, "user": "device-1"}
    events = []
    with client.stream("POST", "/api/tailor", json=body) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events[0]["type"] == "start"
    result = events[-1]
    assert result["type"] == "result", result
    assert result["after"]["must_have"] > result["before"]["must_have"]
    assert any(e["type"] == "progress" and e["stage"] == "validate" for e in events)

    kept_ops = [o for o in result["ops"] if o["op"] != "add"]
    rb = client.post("/api/rebuild", json={"tex": s["tex"], "ops": kept_ops, "analysis": result["analysis"], "evidence": s["evidence"], "skills": s["skills"], "compile": False}).json()
    assert "Deployed the Ledgerly API on Kubernetes" not in rb["tex"]

    fb = client.post("/api/feedback", json={
        "run_id": result["run_id"], "context": result["context"], "arm": result["arm"], "reward": result["reward"], "user": "device-1",
        "decisions": [{"change_id": 0, "action": "kept", "suggested": "a"}, {"change_id": 1, "action": "reverted"}],
    }).json()
    assert 0 <= fb["reward"] <= 1
    stats = client.get("/api/learning").json()["bandit"]
    assert result["context"] in stats


def test_tailor_rejects_empty_jd(client, monkeypatch):
    monkeypatch.setattr(main, "make_llm", lambda req: MockLLM(ANALYSIS, [GOOD_PLAN]))
    s = client.get("/api/sample").json()
    assert client.post("/api/tailor", json={"tex": s["tex"], "jd": "  "}).status_code == 400


def test_rate_limit(client):
    for _ in range(main.LIMITS["models"][0]):
        client.post("/api/models", json={})
    assert client.post("/api/models", json={}).status_code == 429


def test_clean_readme():
    md = "# Ledgerly\n![badge](x.svg) [![ci](y)](z)\n\nA **double-entry** API in [Go](https://go.dev).\n\n```sh\nmake run\n```\n| a | b |\n- Deployed on Kubernetes\n"
    assert clean_readme(md) == "Ledgerly. A double-entry API in Go. Deployed on Kubernetes."


def test_unknown_api_paths_are_404_not_the_web_page(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and "text/html" not in r.headers.get("content-type", "")

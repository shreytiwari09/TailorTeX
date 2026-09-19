import asyncio

import pytest
from fastapi.testclient import TestClient

from conftest import MockLLM
from tailortex.api import main
from tailortex.compile.compile import compile_latex, tex_available
from tailortex.evidence.extract import ExtractedItem, Extraction, extract_plain, extract_with_model, verify
from tailortex.evidence.sources import SourceError, fetch_page, html_to_text, pdf_to_text
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op
from tailortex.pipeline.tailor import background_suggestions
from tailortex.types import EvidenceItem, JobAnalysis, JobTerm

LINKEDIN_TEXT = """Aarav Mehta
Software Engineer at Finch Payments

Experience
Finch Payments
Software Engineer
July 2025 - Present
Built Kafka consumers in Python for settlement events. Migrated 12 services to Kubernetes.

Projects
ChatRelay: a real-time chat server with WebSockets and Redis, used by 300 students.
"""


class ExtractLLM(MockLLM):
    def __init__(self, extraction: dict):
        super().__init__({}, [])
        self.extraction = extraction

    async def complete(self, system, user, schema):
        assert schema is Extraction and "<source" in user
        return Extraction.model_validate(self.extraction)


# --- verification --------------------------------------------------------------------


def test_verify_drops_invented_skills_numbers_and_titles():
    item = ExtractedItem(
        kind="role", title="Software Engineer at Finch Payments",
        text="Built Kafka consumers in Python for settlement events. Cut costs by 40% with Terraform.",
        skills=["Kafka", "Python", "Terraform", "Kubernetes"],
    )
    v = verify(item, LINKEDIN_TEXT)
    assert v.text == "Built Kafka consumers in Python for settlement events."
    assert v.skills == ["Kafka", "Python", "Kubernetes"]
    assert verify(ExtractedItem(title="Harvard", text="Studied at Harvard.", skills=["Rust"]), LINKEDIN_TEXT) is None


async def test_extract_with_model_verifies_every_item():
    llm = ExtractLLM({"items": [
        {"kind": "role", "title": "Software Engineer at Finch Payments", "dates": "July 2025 - Present",
         "text": "Migrated 12 services to Kubernetes. Led a team of 8.", "skills": ["Kubernetes", "Go"]},
        {"kind": "project", "title": "ChatRelay", "text": "A real-time chat server with WebSockets and Redis, used by 300 students.", "skills": ["WebSockets", "Redis"]},
        {"kind": "other", "title": "Made up", "text": "Won the Nobel Prize.", "skills": []},
    ]})
    items = await extract_with_model(llm, LINKEDIN_TEXT, "linkedin", "li")
    assert [i.id for i in items] == ["li1", "li2"]
    assert items[0].text == "Migrated 12 services to Kubernetes." and items[0].skills == ["Kubernetes"]
    assert items[0].title == "Software Engineer at Finch Payments (July 2025 - Present)"
    assert items[1].source == "linkedin" and "300 students" in items[1].text


def test_extract_plain_without_a_model():
    items = extract_plain(LINKEDIN_TEXT, "portfolio", "pf")
    assert items and all(i.source == "portfolio" for i in items)
    assert "Kafka" in {s for i in items for s in i.skills}


# --- sources ---------------------------------------------------------------------------


def test_html_to_text_keeps_content_and_drops_scripts():
    page = """<html><head><title>Aarav · Portfolio</title><meta name="description" content="Backend engineer">
    <script>var secret = 1;</script><style>p{}</style></head>
    <body><nav>Home</nav><h1>Projects</h1><p>ChatRelay &amp; friends: WebSockets<br>and Redis.</p></body></html>"""
    text = html_to_text(page)
    assert text.startswith("Aarav · Portfolio\nBackend engineer")
    assert "ChatRelay & friends: WebSockets\nand Redis." in text
    assert "secret" not in text and "p{}" not in text


@pytest.mark.parametrize("url", ["http://localhost:8000/health", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/"])
def test_fetch_refuses_private_addresses(url):
    with pytest.raises(SourceError, match="private network"):
        asyncio.run(fetch_page(url))


def test_fetch_refuses_other_schemes():
    with pytest.raises(SourceError):
        asyncio.run(fetch_page("file:///etc/passwd"))


def test_pdf_to_text_rejects_non_pdf():
    with pytest.raises(SourceError, match="isn't a PDF"):
        pdf_to_text(b"hello")


@pytest.mark.skipif(not tex_available(), reason="TeX Live not installed")
def test_pdf_to_text_reads_a_real_pdf():
    doc = r"\documentclass{article}\begin{document}Experience\par Finch Payments\par Built Kafka consumers in Python.\end{document}"
    r = compile_latex(doc)
    text = pdf_to_text(r.pdf)
    assert "Finch Payments" in text and "Kafka" in text


# --- endpoint ------------------------------------------------------------------------------


def test_profile_endpoint_with_and_without_a_model(monkeypatch):
    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    main._hits.clear()
    client = TestClient(main.app)
    r = client.post("/api/evidence/profile", json={"kind": "linkedin", "text": LINKEDIN_TEXT}).json()
    assert r["used_model"] is False and r["evidence"] and r["note"]

    llm = ExtractLLM({"items": [{"kind": "project", "title": "ChatRelay", "text": "A real-time chat server with WebSockets and Redis.", "skills": ["WebSockets"]}]})
    llm.model = "mock"
    monkeypatch.setattr(main, "make_llm", lambda req: llm)
    r = client.post("/api/evidence/profile", json={"kind": "portfolio", "text": LINKEDIN_TEXT, "key": "x"}).json()
    assert r["used_model"] is True and r["evidence"][0]["id"] == "pf1" and r["evidence"][0]["source"] == "portfolio"

    bad = client.post("/api/evidence/profile", json={"kind": "portfolio", "url": "http://127.0.0.1:8000/"})
    assert bad.status_code == 400 and "private network" in bad.json()["detail"]
    empty = client.post("/api/evidence/profile", json={"kind": "linkedin"})
    assert empty.status_code == 400


# --- suggestions ---------------------------------------------------------------------------


def test_background_suggestions():
    from pathlib import Path

    tex = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
    doc = parse_resume(tex)
    analysis = JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="Kubernetes", weight=3), JobTerm(term="Python", weight=3)],
                           nice_to_have=[JobTerm(term="WebSockets", weight=1)])
    evidence = [
        EvidenceItem(id="li1", source="linkedin", title="Software Engineer at Finch Payments", text="Migrated 12 services to Kubernetes."),
        EvidenceItem(id="li2", source="linkedin", title="ChatRelay", text="Chat server with WebSockets."),
        EvidenceItem(id="li3", source="linkedin", title="Python work", text="Python everywhere."),  # nothing new
    ]
    ops = [Op(op="add", target="s1.e0", text="Migrated 12 services to Kubernetes", evidence=["li1"])]
    from tailortex.latex.apply import apply_ops

    tailored = parse_resume(apply_ops(doc, ops))
    got = {s["id"]: s for s in background_suggestions(doc, tailored, analysis, evidence, ops)}
    assert set(got) == {"li1", "li2"}
    assert got["li1"]["added"] == ["Kubernetes"] and got["li1"]["cited"] and got["li1"]["must"] == ["Kubernetes"]
    assert got["li2"]["still_missing"] == ["WebSockets"] and not got["li2"]["cited"]

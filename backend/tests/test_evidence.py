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


# --- LinkedIn data archive -------------------------------------------------------------


def make_archive() -> bytes:
    import io
    import zipfile

    files = {
        "Profile.csv": "First Name,Last Name,Headline,Summary\nAarav,Mehta,Backend engineer,I build payment systems in Python.\n",
        "Positions.csv": 'Company Name,Title,Description,Location,Started On,Finished On\nFinch Payments,Software Engineer,"Built Kafka consumers in Python. Migrated 12 services to Kubernetes.",Bengaluru,Jul 2025,\n',
        "Projects.csv": "Title,Description,Url,Started On,Finished On\nChatRelay,Real-time chat server with WebSockets and Redis,https://example.com/chat,2024,\n",
        "Skills.csv": "Name\nPython\nKafka\nGo\n",
        "Certifications.csv": "Name,Url,Authority,Started On,Finished On,License Number\nAWS Certified Developer,,Amazon Web Services,Jan 2025,,\n",
        "Shares.csv": (
            "Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n"
            '2025-08-01 10:00:00,https://x,"Excited to share that our team won the FinHack 2025 hackathon! We built a fraud alert service in Go and Redis.",,,MEMBER_NETWORK\n'
            '2025-06-01 10:00:00,https://x,"Congratulations to my friend on the new role!",,,MEMBER_NETWORK\n'
        ),
        "messages.csv": "FROM,TO,CONTENT\nsomeone,me,private message text\n",
        "Connections.csv": "Notes:\nSome notes line\n\nFirst Name,Last Name\nA,B\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"Basic_LinkedInDataExport/{name}", content)
    return buf.getvalue()


def test_read_archive_only_reads_resume_files():
    from tailortex.evidence.sources import read_linkedin_archive

    archive = read_linkedin_archive(make_archive())
    assert set(archive) == {"profile", "positions", "projects", "skills", "certifications", "shares"}
    assert archive["positions"][0]["company name"] == "Finch Payments"
    with pytest.raises(SourceError, match="isn't a ZIP"):
        read_linkedin_archive(b"not a zip")


def test_archive_items_and_posts_plain():
    from tailortex.evidence.extract import archive_items, posts_plain
    from tailortex.evidence.sources import read_linkedin_archive

    items, skills, posts = archive_items(read_linkedin_archive(make_archive()))
    titles = [i.title for i in items]
    assert titles[0] == "About (LinkedIn)"
    assert "Software Engineer at Finch Payments (Jul 2025)" in titles
    assert "ChatRelay (2024)" in titles and "AWS Certified Developer by Amazon Web Services" in titles
    role = next(i for i in items if "Finch" in i.title)
    assert {"Kafka", "Python", "Kubernetes"} <= set(role.skills)
    assert skills == ["Python", "Kafka", "Go"]
    assert posts.startswith("Post (2025-08-01): Excited")  # newest first
    kept = posts_plain(posts)
    assert len(kept) == 1 and "FinHack 2025" in kept[0].text and kept[0].id == "lp1"


def test_profile_endpoint_archive_and_posts(monkeypatch):
    import base64

    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    main._hits.clear()
    client = TestClient(main.app)
    zip_b64 = base64.b64encode(make_archive()).decode()
    r = client.post("/api/evidence/profile", json={"kind": "linkedin", "zip_base64": zip_b64}).json()
    assert r["replaces"] == ["li", "la", "lp"] and r["skills"] == ["Python", "Kafka", "Go"]
    ids = [e["id"] for e in r["evidence"]]
    assert "lp1" in ids and any(i.startswith("la") for i in ids)
    assert "private message" not in str(r)
    assert "2 posts (1 about your work)" in r["note"]

    llm = ExtractLLM({"items": [{"kind": "achievement", "title": "FinHack 2025", "dates": "2025-08-01",
                                 "text": "Won the FinHack 2025 hackathon with a fraud alert service in Go and Redis.", "skills": ["Go", "Redis", "Rust"]}]})
    llm.model = "mock"
    monkeypatch.setattr(main, "make_llm", lambda req: llm)
    posts = "Excited to share that our team won the FinHack 2025 hackathon! We built a fraud alert service in Go and Redis."
    r = client.post("/api/evidence/profile", json={"kind": "linkedin_posts", "text": posts, "key": "x"}).json()
    assert r["replaces"] == [] and r["used_model"] is True
    item = r["evidence"][0]
    assert item["id"] == "pp1" and item["skills"] == ["Go", "Redis"]  # Rust isn't in the post


# --- links ------------------------------------------------------------------------------


def test_classify_links():
    from tailortex.evidence.links import classify, split_links

    assert classify("github.com/aarav-dev") == ("github_user", {"user": "aarav-dev", "url": "https://github.com/aarav-dev"})
    assert classify("https://github.com/aarav-dev/ledgerly.git/")[0] == "github_repo"
    assert classify("https://github.com/aarav-dev/ledgerly")[1]["repo"] == "ledgerly"
    assert classify("https://www.linkedin.com/in/aarav/")[0] == "linkedin"
    assert classify("in.linkedin.com/in/aarav")[0] == "linkedin"
    assert classify("aarav.github.io")[0] == "portfolio"
    assert classify("https://aarav.dev/projects")[0] == "portfolio"
    assert classify("github.com/settings")[0] == "invalid"
    assert classify("hello")[0] == "invalid"
    assert split_links("github.com/a, aarav.dev\nlinkedin.com/in/a  github.com/a") == ["github.com/a", "aarav.dev", "linkedin.com/in/a"]


def test_links_endpoint(monkeypatch):
    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    main._hits.clear()

    async def fake_best(user, n=6):
        return [EvidenceItem(id=f"gh-{r}", source="github", title=r, text="A project in Go.", skills=["Go"]) for r in ("ledgerly", "chatrelay")]

    async def fake_fetch(url):
        if "broken" in url:
            raise SourceError("Couldn't load that page.")
        return url, "<html><title>Aarav</title><body><h1>Projects</h1><p>ChatRelay: a real-time chat server with WebSockets and Redis, used by 300 students.</p></body></html>"

    monkeypatch.setattr(main, "best_repos", fake_best)
    monkeypatch.setattr(main, "fetch_page", fake_fetch)
    client = TestClient(main.app)
    r = client.post("/api/evidence/links", json={"links": ["github.com/aarav-dev aarav.dev linkedin.com/in/aarav broken.dev nonsense"]}).json()
    by_kind = {x["kind"]: x for x in r["results"] if x["kind"] != "portfolio"}
    portfolios = [x for x in r["results"] if x["kind"] == "portfolio"]
    assert [e["id"] for e in by_kind["github_user"]["evidence"]] == ["gh-ledgerly", "gh-chatrelay"]
    assert by_kind["linkedin"]["evidence"] == [] and "Save to PDF" in by_kind["linkedin"]["note"]
    assert by_kind["invalid"]["error"]
    ok = next(x for x in portfolios if "aarav.dev" in x["link"])
    assert ok["evidence"] and ok["evidence"][0]["source"] == "portfolio"
    assert next(x for x in portfolios if "broken" in x["link"])["error"] == "Couldn't load that page."
    assert r["notes"]  # read without a model


# --- notes and forgetting -----------------------------------------------------------------


def test_notes_become_one_fact_per_line():
    from tailortex.evidence.notes import notes_to_evidence

    items = notes_to_evidence("- Led the robotics club, 12 members\n\n2. At Finch Payments I built Kafka consumers in Python.\n   \n• Speak Spanish")
    assert [(i.id, i.text) for i in items] == [
        ("n1", "Led the robotics club, 12 members"),
        ("n2", "At Finch Payments I built Kafka consumers in Python."),
        ("n3", "Speak Spanish"),
    ]
    assert items[1].source == "fact" and {"Kafka", "Python"} <= set(items[1].skills)


def test_notes_back_a_new_bullet_but_nothing_more():
    from pathlib import Path

    from tailortex.evidence.notes import notes_to_evidence
    from tailortex.validate.validate import ValidationContext, validate_ops

    tex = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()
    ctx = ValidationContext(doc=parse_resume(tex), evidence=notes_to_evidence("At Finch Payments I built Kafka consumers in Python."))
    ok = Op(op="add", target="s1.e0", text="Built Kafka consumers in Python", evidence=["n1"])
    bad = Op(op="add", target="s1.e0", text="Built Kafka consumers in Python handling 2M events a day", evidence=["n1"])
    r = validate_ops([ok, bad], ctx)
    assert len(r.valid) == 1 and r.violations[0].rule == "invented_number"


def test_forget_deletes_this_devices_learning_data(monkeypatch, tmp_path):
    monkeypatch.setenv("TAILORTEX_API_KEY", "")
    from tailortex.learn.bandit import Bandit
    from tailortex.learn.style import StyleMemory

    Bandit().update("backend|mid", "balanced", 1.0, user="device-9")
    StyleMemory().record("device-9", ["kept bullet"], [])
    client = TestClient(main.app)
    assert client.post("/api/forget", json={"user": "device-9"}).json() == {"deleted": True}
    assert StyleMemory().get("device-9") == ([], [])
    assert "device-9" not in Bandit().store.load().get("users", {})
    assert Bandit().stats()["backend|mid"]["balanced"]["n"] == 1.0  # the anonymous global count stays
    assert client.post("/api/forget", json={"user": "device-9"}).json() == {"deleted": False}

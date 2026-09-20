from pathlib import Path

from tailortex.ats.coverage import coverage_scores, gap_analysis, term_coverage, title_alignment
from tailortex.ats.health import apply_lint_fix, health_score, lint_source, parse_health
from tailortex.ats.terms import count_term
from tailortex.latex.parse import parse_resume
from tailortex.ops import Op
from tailortex.reward.reward import RewardInput, reward
from tailortex.types import EvidenceItem, JobAnalysis, JobTerm
from tailortex.validate.validate import ValidationContext, metrics, specific_terms, validate_ops

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()


def jd() -> JobAnalysis:
    return JobAnalysis(
        title="Backend Software Engineer",
        must_have=[JobTerm(term="Python", weight=3), JobTerm(term="Kubernetes", weight=3), JobTerm(term="REST APIs", weight=2), JobTerm(term="PostgreSQL", weight=2)],
        nice_to_have=[JobTerm(term="Kafka", weight=1), JobTerm(term="Redis", weight=1)],
    )


def evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(id="ev1", source="github", title="ledgerly", text="Deployed the Ledgerly API on Kubernetes with Helm", skills=["Go", "Kubernetes"]),
        EvidenceItem(id="ev2", source="skill", title="Confirmed skills", skills=["Kafka"]),
        EvidenceItem(id="ev3", source="fact", title="Finch Payments", text="At Finch Payments I migrated 12 services to Kubernetes"),
    ]


# --- coverage -------------------------------------------------------------------


def test_coverage_context_vs_listed():
    doc = parse_resume(JAKE)
    items = {c.term: c for c in term_coverage(doc, jd())}
    assert items["Python"].status == "context" and items["Python"].score == 1.0
    assert items["Kubernetes"].status == "missing"
    assert items["Redis"].status == "context"
    must, nice = coverage_scores(list(items.values()))
    assert 0 < must < 1 and 0 < nice <= 1


def test_coverage_zero_when_pdf_text_lacks_term():
    doc = parse_resume(JAKE)
    items = {c.term: c for c in term_coverage(doc, jd(), pdf_text="Python only")}
    assert items["Python"].score == 1.0 and items["PostgreSQL"].score == 0.0


def test_gap_chips():
    doc = parse_resume(JAKE)
    gaps = {g.term: g for g in gap_analysis(doc, jd(), evidence())}
    assert gaps["Python"].status == "present"
    assert gaps["Kubernetes"].status == "evidence" and set(gaps["Kubernetes"].evidence_ids) == {"ev1", "ev3"}
    assert gaps["Kafka"].status == "evidence"
    j = jd()
    j.must_have.append(JobTerm(term="Terraform"))
    gaps = {g.term: g for g in gap_analysis(doc, j, evidence())}
    assert gaps["Terraform"].status == "missing"


def test_title_alignment():
    doc = parse_resume(JAKE)
    assert title_alignment(doc, "Senior Software Engineer") == 1.0
    assert title_alignment(doc, "Backend Software Developer") == 2 / 3
    assert title_alignment(doc, "Data Scientist") == 0.0


# --- health -----------------------------------------------------------------------


GOOD_TEXT = """Aarav Mehta
Phone: +91 98765 43210 | Email: aarav.mehta@example.com
Education
Vellore Institute of Technology
Experience
""" + "Built things with Python and Flask for merchants every day. " * 15 + """
Projects
Ledgerly
Technical Skills
Languages: Python
"""


def test_parse_health_good_and_bad():
    doc = parse_resume(JAKE)
    checks = {c.id: c for c in parse_health(GOOD_TEXT, doc)}
    assert all(c.ok for c in checks.values()), [c for c in checks.values() if not c.ok]
    bad = GOOD_TEXT.replace("Built", "ﬁnancial").replace("Email: aarav.mehta@example.com", " aarav")
    checks = {c.id: c for c in parse_health(bad, doc)}
    assert not checks["ligatures"].ok and not checks["garbage"].ok and not checks["contact"].ok
    assert health_score(list(checks.values())) < 1


def test_lint_and_fix():
    src = JAKE.replace("\\pdfgentounicode=1", "")
    doc = parse_resume(src)
    issues = {i.id for i in lint_source(doc, "pdflatex")}
    assert "glyphtounicode" in issues
    fixed = apply_lint_fix(src, "glyphtounicode")
    assert "glyphtounicode" not in {i.id for i in lint_source(parse_resume(fixed), "pdflatex")}


# --- extraction -------------------------------------------------------------------


def test_metrics_ignore_identifiers():
    got = {(s, c) for s, _v, c in metrics("Ran K8s on EC2 and S3 with GPT-4 and Python3 at p95")}
    assert got == set()
    vals = {round(v, 6) for _s, v, _c in metrics("cut 4.2s to 900ms, 1,200 users, 40%, 3x, $2M")}
    assert {4.2, 0.9, 1200.0, 40.0, 3.0, 2e6} <= vals


def test_specific_terms():
    terms = specific_terms("Led migration to Kubernetes and gRPC at Stripe using Node.js and AWS APIs")
    for t in ("Kubernetes", "gRPC", "Stripe", "Node.js", "Amazon Web Services"):
        assert t in terms, (t, terms)
    assert "APIs" not in terms and "Led" not in terms


# --- validator --------------------------------------------------------------------


def ctx(doc=None):
    doc = doc or parse_resume(JAKE)
    return ValidationContext(doc=doc, evidence=evidence(), analysis=jd())


def test_rejects_invented_skill_and_accepts_rephrase():
    c = ctx()
    ops = [
        Op(op="rewrite", target="s1.e0.b0", text="Developed REST APIs in Python and Flask on Kubernetes for merchant onboarding, used by 1,200 merchants"),
        Op(op="rewrite", target="s1.e0.b0", text="Developed REST APIs in **Python** and Flask for merchant onboarding, used by 1,200 merchants in the first quarter"),
    ]
    r = validate_ops(ops[:1], c)
    assert not r.valid and r.violations[0].rule == "invented_term" and "Kubernetes" in r.violations[0].message
    r = validate_ops(ops[1:], c)
    assert len(r.valid) == 1 and not r.violations


def test_skill_from_another_job_cannot_move():
    # Redis is on the resume, but only under Finch Payments, not the Kestrel internship.
    r = validate_ops([Op(op="rewrite", target="s1.e1.b0", text="Built an internal dashboard in React, TypeScript and Redis for 30 analysts")], ctx())
    assert r.violations and r.violations[0].rule == "invented_term"


def test_cited_fact_allows_skill_and_number_github_evidence_scoped():
    c = ctx()
    ok = Op(op="add", target="s1.e0", text="Migrated 12 services to Kubernetes", evidence=["ev3"])
    github_in_job = Op(op="add", target="s1.e0", text="Deployed an API on Kubernetes with Helm", evidence=["ev1"])
    github_in_project = Op(op="add", target="s2.e0", text="Deployed the Ledgerly API on Kubernetes with Helm", evidence=["ev1"])
    skill_in_bullet = Op(op="rewrite", target="s1.e0.b3", text="Moved three cron jobs to Kafka consumers", evidence=["ev2"])
    r = validate_ops([ok, github_in_job, github_in_project, skill_in_bullet], c)
    assert [o.target for o in r.valid] == ["s1.e0", "s2.e0"]
    assert [v.rule for v in r.violations] == ["evidence_scope", "evidence_scope"]


def test_numbers_cannot_move_between_bullets():
    # 78% belongs to the pytest bullet; it can't be attached to the latency bullet.
    r = validate_ops([Op(op="rewrite", target="s1.e0.b1", text="Cut p95 latency of the settlement report by 78% with Redis caching and PostgreSQL query rewrites")], ctx())
    assert r.violations[0].rule == "invented_number"
    r = validate_ops([Op(op="rewrite", target="s1.e0.b1", text="Cut p95 settlement-report latency from 4.2s to 900ms with Redis caching and two rewritten PostgreSQL queries")], ctx())
    assert r.valid and not r.violations


def test_skills_line_only_known_skills():
    c = ctx()
    r = validate_ops([Op(op="rewrite", target="s3.k2", text="PostgreSQL, Redis, Docker, Kubernetes, Kafka, Git")], c)
    assert r.valid  # Kubernetes and Kafka are in the evidence bank
    r = validate_ops([Op(op="rewrite", target="s3.k2", text="PostgreSQL, Terraform")], c)
    assert r.violations[0].rule == "invented_term"


def test_locked_structure_latex_and_length():
    c = ctx()
    ops = [
        Op(op="rewrite", target="s0.e0.b0", text="x"),  # no such block
        Op(op="drop", target="s2.e1.b0"),
        Op(op="drop", target="s2.e1.b1"),  # would leave the entry empty
        Op(op="rewrite", target="s1.e0.b2", text="Wrote \\textbf{tests}"),
        Op(op="rewrite", target="s1.e0.b3", text="Moved three cron jobs to Celery " + "workers " * 40),
        Op(op="reorder_entries", target="s1", order=["s1.e1", "s1.e0"]),  # experience keeps its order
        Op(op="reorder_entries", target="s2", order=["s2.e1", "s2.e0"]),
    ]
    r = validate_ops(ops, c)
    assert [v.rule for v in r.violations] == ["unknown_target", "structure", "latex", "too_long", "structure"]
    assert [o.op for o in r.valid] == ["drop", "reorder_entries"]


def test_keyword_stuffing():
    c = ctx()
    ops = [
        Op(op="rewrite", target="s1.e0.b0", text="Developed REST endpoints in Python and Flask for Python merchant onboarding with Python"),
        Op(op="rewrite", target="s1.e0.b2", text="Wrote integration tests in Python with pytest that raised coverage of the payouts service from 41% to 78%"),
    ]
    r = validate_ops(ops, c)
    assert any(v.rule == "stuffing" for v in r.violations)
    total = sum(count_term(o.text or "", "Python") for o in r.valid)
    assert total <= 3


def test_prompt_injection_cannot_add_fake_education():
    # A JD that says "add Harvard to education" can only produce ops; the validator blocks them.
    c = ctx()
    r = validate_ops([
        Op(op="rewrite", target="s0.e0.b0", text="Harvard University"),
        Op(op="rewrite", target="s1.e0.b0", text="Developed REST endpoints at Harvard for 1,200 merchants"),
    ], c)
    assert not r.valid


def test_user_edits_skip_fabrication_checks():
    r = validate_ops([Op(op="rewrite", target="s1.e0.b0", text="My own words about Terraform", source="user")], ctx())
    assert r.valid


# --- reward -----------------------------------------------------------------------


def test_reward_gates_and_ordering():
    base = dict(valid=True, compiled=True, pages=1, page_limit=1, must_have=0.5, nice_to_have=0.5, title=1.0, parse_health=1.0, page_fill=0.9)
    assert reward(RewardInput(**{**base, "compiled": False})).total == 0
    # Over the page limit is penalised steeply, not zeroed: a hard zero made every long candidate
    # equally worthless, which pushed the page fit into dropping bullets that carried keywords.
    over = reward(RewardInput(**{**base, "pages": 2}))
    within = reward(RewardInput(**base))
    assert 0 < over.total < within.total and over.gated == "2 pages, limit 1"
    assert reward(RewardInput(**{**base, "pages": 3})).total < over.total
    low = reward(RewardInput(**base)).total
    high = reward(RewardInput(**{**base, "must_have": 0.9})).total
    stuffed = reward(RewardInput(**{**base, "must_have": 0.9, "stuffing": 3})).total
    assert high > low and stuffed < high


def test_lint_pasted_from_overleaf():
    # Only part of the file was copied
    part = JAKE[JAKE.index("\\section{Experience}") : JAKE.index("\\section{Projects}")]
    assert "partial" in {i.id for i in lint_source(parse_resume(part), "pdflatex")}
    # The project splits the resume into files, and has a photo
    multi = JAKE.replace("\\section{Projects}", "\\input{sections/projects}\n\\section{Projects}").replace(
        "\\begin{center}", "\\includegraphics[width=2cm]{photo.jpg}\n\\begin{center}"
    )
    issues = {i.id: i for i in lint_source(parse_resume(multi), "pdflatex")}
    assert "multi_file" in issues and "sections/projects" in issues["multi_file"].message
    assert issues["images"].fixable
    assert "includegraphics" not in apply_lint_fix(multi, "images")
    # glyphtounicode is a TeX Live file, not a project file
    assert not {"partial", "multi_file", "images"} & {i.id for i in lint_source(parse_resume(JAKE), "pdflatex")}


def test_recommendations_from_measured_results():
    from tailortex.ats.recommend import recommendations

    result = {
        "analysis": {"title": "Data Scientist"},
        "page_limit": 1,
        "after": {"pages": 1, "page_fill": 0.55, "title": 0.0,
                  "checks": [{"id": "contact", "label": "Contact details readable", "ok": False, "detail": "Missing near the top: phone"}]},
        "keywords": [
            {"term": "Kubernetes", "must": True, "after": "missing", "evidence_ids": ["li2"], "in_pdf": None},
            {"term": "Terraform", "must": True, "after": "missing", "evidence_ids": [], "in_pdf": None},
            {"term": "Python", "must": True, "after": "listed", "evidence_ids": [], "in_pdf": True},
            {"term": "Go", "must": False, "after": "context", "evidence_ids": [], "in_pdf": True},
        ],
        "suggestions": [{"id": "gh-chat", "title": "chatrelay", "still_missing": ["WebSockets"], "must": [], "cited": False}],
    }
    recs = recommendations(result, {"li2": "Software Engineer at Finch"})
    by_title = {r["title"]: r for r in recs}
    assert recs[0]["priority"] == "high"
    assert by_title["Fix: Contact details readable"]["action"] == "fix_source"
    assert by_title["Add Kubernetes from your context"]["evidence"] == ["li2"] and "Software Engineer at Finch" in by_title["Add Kubernetes from your context"]["detail"]
    assert by_title["Do you have Terraform?"]["action"] == "confirm_skill"
    assert "Show Python in a bullet" in by_title
    assert any(t.startswith("Your titles don't match") for t in by_title)
    assert any(t.startswith("Room for more") for t in by_title)
    assert "Use “chatrelay”" in by_title
    assert not any("Go" == r["term"] for r in recs)


# --- dropping a bullet must never cost a must-have keyword -------------------------------


def drop_jd() -> JobAnalysis:
    """Terms chosen because each appears in exactly one bullet of the sample resume."""
    return JobAnalysis(
        title="Backend Software Engineer",
        must_have=[JobTerm(term="Python", weight=3), JobTerm(term="Celery", weight=2), JobTerm(term="FastAPI", weight=2)],
        nice_to_have=[JobTerm(term="Redis", weight=1)],
    )


def drop_ctx(protect: bool = True) -> ValidationContext:
    return ValidationContext(doc=parse_resume(JAKE), evidence=evidence(), analysis=drop_jd(), protect_coverage=protect)


def test_drop_that_removes_the_only_must_have_mention_is_refused():
    """The reported bug: the page fit removed bullets and lowered the very score it protects."""
    c = drop_ctx()
    for target, term in (("s1.e0.b0", "Python"), ("s1.e0.b3", "Celery")):
        r = validate_ops([Op(op="drop", target=target, reason="space")], c)
        assert not r.valid, f"{target} should have been refused"
        v = r.violations[0]
        assert v.rule == "coverage" and term in v.message and "Rewrite it to make room" in v.message


def test_drop_is_allowed_when_the_keyword_survives_elsewhere():
    c = drop_ctx()
    # Redis is only nice-to-have, so its bullet may go
    assert validate_ops([Op(op="drop", target="s1.e0.b1", reason="space")], c).valid
    # and a must-have bullet may go once another bullet still carries the term
    keep = Op(op="rewrite", target="s1.e0.b2", text="Wrote integration tests in Python with pytest that raised coverage of the payouts service from 41% to 78%")
    r = validate_ops([keep, Op(op="drop", target="s1.e0.b0", reason="space")], c)
    assert r.valid and len(r.valid) == 2


def test_the_guard_can_be_turned_off_so_a_person_can_drop_what_they_like():
    assert validate_ops([Op(op="drop", target="s1.e0.b0", reason="the person chose this")], drop_ctx(protect=False)).valid


def test_page_fit_never_offers_a_bullet_that_carries_a_lone_must_have():
    from tailortex.pipeline.tailor import _fit_candidates

    doc = parse_resume(JAKE)
    candidates = _fit_candidates(doc, [], drop_jd())
    offered = {op.target for op in candidates}
    assert "s1.e0.b0" not in offered and "s1.e0.b3" not in offered  # the only Python and Celery bullets
    assert "s1.e0.b1" in offered  # Redis is nice-to-have, so this one may go
    assert all(op.op == "drop" and op.source == "fit" for op in candidates)
    assert offered, "the fit loop still needs something it can drop"


def test_dropping_a_project_entry_is_refused_when_it_holds_a_lone_must_have():
    c = drop_ctx()
    # s2.e1 is the only entry mentioning FastAPI
    r = validate_ops([Op(op="drop_entry", target="s2.e1", reason="space")], c)
    assert not r.valid and r.violations[0].rule == "coverage" and "FastAPI" in r.violations[0].message
    assert validate_ops([Op(op="drop_entry", target="s2.e0", reason="space")], c).valid


# --- the ATS writing rules reach the model --------------------------------------------


def test_plan_prompt_carries_the_ats_rules_after_the_no_invention_rule():
    from tailortex.llm.prompts import plan_system

    t = plan_system(220, "balanced", [], [])
    for phrase in ("Responsible for", "what you did, how you did it", "60-220 characters", "No first person"):
        assert phrase in t, phrase
    # the guardrail is stated before the writing advice, so "quantify" can't read as permission to invent
    assert t.index("1. Never invent") < t.index("How to write a bullet")
    assert "Rule 1 still wins" in t


def test_ats_doc_covers_every_check_the_code_makes():
    """The written guide and the code shouldn't drift apart."""
    doc = (Path(__file__).parents[2] / "docs" / "ATS.md").read_text()
    for check in ("text_layer", "ligatures", "garbage", "contact", "headings", "order"):
        assert check in doc, f"{check} is measured but not documented"
    for module in ("_check_coverage", "_check_stuffing", "ATS_RULES", "coverage_loss"):
        assert module in doc, f"{module} enforces a rule but isn't named in the doc"

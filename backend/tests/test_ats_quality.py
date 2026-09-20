"""General resume quality: the checks that raise a score on any job, not just the one being applied to."""

from pathlib import Path

from tailortex.ats.health import Check, health_score
from tailortex.ats.quality import (
    MAX_BULLET,
    MIN_BULLET,
    _has_structure,
    _opens_strongly,
    quality_checks,
    quality_findings,
    quality_report,
)
from tailortex.ats.quality import _first_person, result_metrics
from tailortex.latex.parse import parse_resume

JAKE = (Path(__file__).parents[1] / "tailortex" / "templates" / "jake" / "resume.tex").read_text()

# The template's first job, so a whole-resume test can change known bullets.
FIRST_JOB = [
    "Developed REST endpoints in Python and Flask for merchant onboarding, used by 1,200 merchants in the first quarter",
    "Cut the p95 latency of the settlement report from 4.2s to 900ms by adding Redis caching and rewriting two PostgreSQL queries",
    "Wrote integration tests with pytest that raised coverage of the payouts service from 41\\% to 78\\%",
    "Moved three cron jobs to Celery workers and added retries, ending the missed nightly reconciliations",
]


def with_bullets(bullets: list[str]) -> str:
    """The sample resume with its first job's bullets replaced."""
    tex = JAKE
    for i, original in enumerate(FIRST_JOB):
        marker = f"\\resumeItem{{{original}}}"
        assert marker in tex, original
        tex = tex.replace(marker, f"\\resumeItem{{{bullets[i]}}}" if i < len(bullets) else "", 1)
    return tex


def scores(tex: str) -> dict[str, float]:
    return {c.id: (c.score if c.score is not None else float(c.ok)) for c in quality_checks(parse_resume(tex))}


# --- how a single bullet reads ------------------------------------------------------------


def test_a_bullet_opens_strongly_with_a_verb_doing_work():
    for good in (
        "Built a payments API in Python that cut manual reconciliation from 3 hours to 20 minutes",
        "Containerized the ingestion service with Docker, cutting deploy time from 40 to 6 minutes",  # no verb list has this
        "Moved three cron jobs to Celery workers, ending the missed nightly reconciliation",
    ):
        assert _opens_strongly(good), good
    for weak in (
        "Responsible for maintaining the payments API and fixing bugs reported by support",
        "Worked on the billing service to add retries for the nightly reconciliation job",
        "Helped the data team define a schema for event logs",
        "Building a dashboard in React that replaced a weekly spreadsheet",  # a gerund
        "The billing service was rewritten in Go, which removed the nightly failures",  # an article
        "Duties included running the weekly deploy and triaging support tickets",
    ):
        assert not _opens_strongly(weak), weak


def test_a_bullet_says_how_it_was_done_or_what_changed():
    for good in (
        "Moved three cron jobs to Celery workers and added retries, ending the missed reconciliation",  # , + gerund
        "Added a PostgreSQL locking scheme that removed race conditions in concurrent transfers",  # that + verb
        "Rewrote the importer using a streaming parser, so that memory stayed flat on large files",  # how + so that
        "Cut p95 latency from 4.2s to 900ms",  # a metric is a result
    ):
        assert _has_structure(good), good
    assert not _has_structure("Designed the FastAPI backend and a React frontend for the admin tool")


def test_structure_does_not_charge_twice_for_a_weak_opener():
    """action_verb already counts the opener; structure asks a different question."""
    weak_but_clear = "Worked with the data team to define the schema for event logs, reducing malformed records by 60%"
    assert not _opens_strongly(weak_but_clear) and _has_structure(weak_but_clear)


def test_quantified_counts_results_not_version_numbers():
    assert result_metrics("Cut p95 latency from 4.2s to 900ms")
    assert result_metrics("Rolled the change out to 1,200 merchants in the first quarter")
    # a version or language edition says nothing about impact
    assert not result_metrics("Migrated the service to Python 3 and Django 4.2")
    assert not result_metrics("Wrote 3 scripts")


# --- the resume as a whole ----------------------------------------------------------------


def test_weak_bullets_pull_the_score_down_and_good_ones_hold_it_up():
    weak = with_bullets([
        "Responsible for the payments API and its nightly reconciliation run",
        "Worked on the settlement report and the caching layer for the team",
        "Helped with integration tests for the payouts service each release",
        "Duties included moving cron jobs and monitoring the nightly batch",
    ])
    assert scores(weak)["action_verb"] < scores(JAKE)["action_verb"]
    strong = with_bullets([
        "Built a payments API in Python that cut manual reconciliation from 3 hours to 20 minutes",
        "Migrated twelve services to Kubernetes, ending the weekly deploy freeze for the platform",
        "Rewrote the settlement report query, dropping p95 latency from 4.2s to 900ms",
        "Automated the nightly batch with Celery retries, ending the missed reconciliations",
    ])
    # the rest of the sample still holds one weak opener, so this is the sample's own ceiling
    assert scores(strong)["action_verb"] == scores(JAKE)["action_verb"] > scores(weak)["action_verb"]


def test_half_the_bullets_carrying_a_number_is_already_full_marks():
    """Not every bullet can be quantified honestly, and we never invent one to reach a target."""
    assert scores(JAKE)["quantified"] == 1.0  # 7 of 11
    none = with_bullets([
        "Built a payments API in Python for merchant onboarding across the platform",
        "Rewrote the settlement report query and the caching layer for the team",
        "Added integration tests for the payouts service before each release",
        "Moved the nightly cron jobs onto Celery workers with retries",
    ])
    assert scores(none)["quantified"] < scores(JAKE)["quantified"]


def test_first_person_is_flagged_but_a_lowercase_stray_letter_is_not():
    mine = with_bullets(["Built the reporting service that my team used to close the books each month"])
    assert scores(mine)["third_person"] < 1.0
    assert _first_person("Built the reporting service that my team used each month")
    assert not _first_person("Shipped a CLI that reads i-node metadata and reports stale files")


def test_bullets_that_are_too_short_or_too_long_are_flagged():
    assert (MIN_BULLET, MAX_BULLET) == (60, 240)
    assert scores(with_bullets(["Fixed a bug"]))["length"] < 1.0
    long_one = "Built " + "a long description of this piece of work " * 8
    assert len(long_one) > MAX_BULLET
    assert scores(with_bullets([long_one]))["length"] < 1.0
    assert scores(JAKE)["length"] == 1.0


def test_repeating_one_opening_verb_is_flagged():
    same = with_bullets([f"Built service {n} in Python that cut the nightly run by {n} minutes" for n in range(1, 5)])
    assert scores(same)["verb_variety"] < 1.0
    assert scores(JAKE)["verb_variety"] == 1.0


def test_a_date_style_only_has_to_agree_within_a_section():
    """A project dated 2024 beside a job dated Aug. 2021 - May 2025 is ordinary resume style."""
    assert scores(JAKE)["dates"] == 1.0
    undated = JAKE.replace("{Jul. 2025 -- Present}", "{}", 1)
    assert scores(undated)["dates"] < 1.0


def test_a_check_with_nothing_to_measure_is_left_out_not_failed():
    bare = (
        "\\documentclass{article}\n\\begin{document}\n\\section{Skills}\n"
        "\\begin{itemize}\\item Languages: Python, Go\\end{itemize}\n\\end{document}\n"
    )
    ids = {c.id for c in quality_checks(parse_resume(bare))}
    assert "dates" not in ids and "action_verb" not in ids
    assert quality_report(parse_resume(bare))[0] > 0.5  # not docked for what it doesn't have


def test_a_layout_table_is_flagged_but_a_heading_row_is_not():
    assert scores(JAKE)["layout"] == 1.0  # its two-column heading rows are harmless
    boxed = JAKE.replace("\\section{Experience}", "\\section{Experience}\n\\begin{multicols}{2}", 1).replace(
        "\\section{Projects}", "\\end{multicols}\n\\section{Projects}", 1)
    assert scores(boxed)["layout"] == 0.0


def test_the_shipped_template_scores_well():
    """A canary: if a new check is too harsh, the product's own sample fails it first."""
    score, checks, _ = quality_report(parse_resume(JAKE))
    assert score >= 0.9, {c.id: c.score for c in checks}


def test_findings_name_the_block_and_say_what_to_do():
    doc = parse_resume(with_bullets(["Responsible for the billing service and its nightly reconciliation run"]))
    found = [f for f in quality_findings(doc) if "Responsible for" in f.text]
    kinds = {f.check for f in found}
    assert {"action_verb", "quantified"} <= kinds
    verb = next(f for f in found if f.check == "action_verb")
    assert verb.block_id.startswith("s") and "Built, Led" in verb.hint


def test_a_graded_check_contributes_its_score_not_just_pass_or_fail():
    checks = [Check("a", "A", ok=False, detail="", weight=1.0, score=0.5), Check("b", "B", ok=True, detail="", weight=1.0)]
    assert health_score(checks) == 0.75  # 0.5 + 1.0 over 2
    assert health_score([Check("c", "C", ok=True, detail="", weight=2.0)]) == 1.0  # ungraded still works


# --- it reaches the score and the recommendations -------------------------------------


def test_quality_reaches_the_reward_instead_of_a_constant():
    """bullet_quality was declared and weighted 0.10 but never populated, so it was always 0.5."""
    from tailortex.pipeline.tailor import measure
    from tailortex.reward.reward import WEIGHTS, RewardInput, reward
    from tailortex.types import JobAnalysis, JobTerm

    jd = JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="Python", weight=3)])
    good, _ = measure(parse_resume(JAKE), jd, None)
    weak_tex = with_bullets([
        "Responsible for the payments API and its nightly reconciliation run",
        "Worked on the settlement report and the caching layer for the team",
        "Helped with integration tests for the payouts service each release",
        "Duties included moving cron jobs and monitoring the nightly batch",
    ])
    weak, _ = measure(parse_resume(weak_tex), jd, None)

    assert good.quality > weak.quality and weak.quality != 0.5
    assert WEIGHTS["bullet_quality"] == 0.10

    def score(m):
        return reward(RewardInput(valid=True, compiled=True, pages=1, page_limit=1, must_have=1.0, nice_to_have=1.0,
                                  title=1.0, parse_health=1.0, page_fill=0.9, bullet_quality=m.quality)).total

    # with keyword coverage identical, the better-written resume now wins
    assert score(good) > score(weak)


def test_writing_problems_become_recommendations_with_examples():
    from tailortex.ats.recommend import recommendations
    from tailortex.pipeline.tailor import measure
    from tailortex.types import JobAnalysis, JobTerm

    weak_tex = with_bullets([
        "Responsible for the payments API and its nightly reconciliation run",
        "Worked on the settlement report and the caching layer for the team",
        "Helped with integration tests for the payouts service each release",
        "Duties included moving cron jobs and monitoring the nightly batch",
    ])
    m, _ = measure(parse_resume(weak_tex), JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="Python", weight=3)]), None)
    writing = [r for r in recommendations({"after": m.to_dict(), "analysis": {}}) if r["group"] == "Writing"]

    assert {r["term"] for r in writing} >= {"action_verb", "structure"}
    verb = next(r for r in writing if r["term"] == "action_verb")
    assert verb["action"] == "improve_writing"
    assert any("Responsible for" in ex for ex in verb["evidence"])  # quotes the offending bullets
    # a resume that passes a check isn't nagged about it
    good, _ = measure(parse_resume(JAKE), JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="Python", weight=3)]), None)
    assert not [r for r in recommendations({"after": good.to_dict(), "analysis": {}}) if r["term"] == "quantified"]


# --- what a change is worth ---------------------------------------------------------------


def _jd():
    from tailortex.types import JobAnalysis, JobTerm

    return JobAnalysis(
        title="Backend Engineer",
        must_have=[JobTerm(term="PyTorch", weight=3), JobTerm(term="Python", weight=3), JobTerm(term="Kubernetes", weight=2),
                   JobTerm(term="PostgreSQL", weight=2), JobTerm(term="Terraform", weight=1)],
        nice_to_have=[JobTerm(term="Kafka", weight=1), JobTerm(term="Redis", weight=1)],
    )


def test_a_missing_must_have_is_worth_its_share_of_the_must_have_weight():
    """The +11% in the design: 0.40 * 3 / (3+3+2+2+1) = 0.109."""
    from tailortex.ats.gain import term_gain

    assert abs(term_gain(_jd(), "PyTorch") - 0.109) < 0.001
    assert abs(term_gain(_jd(), "Terraform") - 0.0364) < 0.001  # a passing mention is worth a third as much
    assert abs(term_gain(_jd(), "Kafka") - 0.075) < 0.001  # nice-to-haves share 0.15 between two terms
    assert term_gain(_jd(), "Rust") == 0.0  # not part of this job


def test_promoting_a_listed_skill_into_a_bullet_is_worth_forty_percent_of_a_new_one():
    from tailortex.ats.gain import term_gain

    full, promote = term_gain(_jd(), "PyTorch"), term_gain(_jd(), "PyTorch", "listed", "context")
    assert abs(promote - full * 0.4) < 0.001
    assert term_gain(_jd(), "PyTorch", "context", "missing") == -full  # losing it costs exactly what gaining it earns


def test_term_gain_equals_the_real_coverage_change():
    """Proved against the real scoring function, not by restating its formula."""
    from tailortex.ats.coverage import TermCoverage, coverage_scores
    from tailortex.ats.gain import term_gain
    from tailortex.reward.reward import WEIGHTS

    jd = _jd()

    def must_score(overrides: dict[str, tuple[str, float]]) -> float:
        items = [TermCoverage(t.term, t.weight, True, 0, 0, *overrides.get(t.term, ("missing", 0.0)))
                 for t in jd.must_have]
        return coverage_scores(items)[0]

    base = must_score({})
    for t in jd.must_have:
        moved = must_score({t.term: ("context", 1.0)})
        assert abs(WEIGHTS["must_have"] * (moved - base) - term_gain(jd, t.term)) < 1e-4, t.term


def test_per_change_gains_credit_a_keyword_to_the_first_change_only():
    from tailortex.ats.gain import per_change_gains
    from tailortex.ops import Op

    doc = parse_resume(JAKE)
    jd = _jd()
    first = Op(op="rewrite", target="s1.e0.b2", text="Wrote integration tests in Python and Kubernetes that raised coverage of the payouts service from 41% to 78%")
    second = Op(op="rewrite", target="s1.e1.b2", text="Worked with the data team on Kubernetes to define the schema for event logs, reducing malformed records by 60%")
    gains = per_change_gains(doc, [first, second], jd)
    assert "Kubernetes" in gains[0]["terms"] and "Kubernetes" not in gains[1]["terms"]
    assert gains[0]["gain"] > 0 and gains[1]["gain"] == 0.0  # the second adds nothing new


def test_a_drop_that_removes_the_last_mention_scores_negative():
    from tailortex.ats.gain import per_change_gains
    from tailortex.ops import Op

    from tailortex.types import JobAnalysis, JobTerm

    # Celery appears in exactly one bullet of the sample (s1.e0.b3); PostgreSQL appears in two
    lone = JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="Celery", weight=2), JobTerm(term="Python", weight=2)])
    gains = per_change_gains(parse_resume(JAKE), [Op(op="drop", target="s1.e0.b3", source="fit")], lone)
    assert gains[0]["gain"] < 0 and gains[0]["terms"] == []
    # dropping a bullet whose keyword survives elsewhere costs nothing
    shared = JobAnalysis(title="Backend Engineer", must_have=[JobTerm(term="PostgreSQL", weight=2)])
    assert per_change_gains(parse_resume(JAKE), [Op(op="drop", target="s2.e0.b1", source="fit")], shared)[0]["gain"] == 0.0


def test_gap_gains_rank_the_unbacked_skills_by_worth_and_skip_what_is_covered():
    from tailortex.ats.gain import gap_gains
    from tailortex.ats.coverage import gap_analysis, term_coverage
    from tailortex.pipeline.tailor import keyword_table

    doc, jd = parse_resume(JAKE), _jd()
    gaps = gap_analysis(doc, jd, [])
    cov = term_coverage(doc, jd)
    found = gap_gains(jd, [g.to_dict() for g in gaps], keyword_table(cov, cov, gaps))
    terms = [g["term"] for g in found]
    assert "PyTorch" in terms and "Python" not in terms  # Python is already on the resume
    assert found == sorted(found, key=lambda g: -g["gain"])
    assert found[0]["term"] == "PyTorch" and abs(found[0]["gain"] - 0.109) < 0.001


def test_the_displayed_score_uses_the_reward_weights_and_is_not_page_gated():
    from tailortex.ats.gain import ats_score
    from tailortex.reward.reward import WEIGHTS

    m = {"must_have": 0.5, "nice_to_have": 0.5, "title": 1.0, "health": 1.0, "page_fill": 0.85, "quality": 0.5}
    expected = 0.40 * 0.5 + 0.15 * 0.5 + 0.10 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0 + 0.10 * 0.5
    assert abs(ats_score(m) - expected) < 1e-4 and abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert ats_score({**m, "pages": 3}) == ats_score(m)  # a long resume still has a real score
    assert ats_score({**m, "must_have": 1.0}) > ats_score(m)


def test_a_result_carries_the_score_the_gains_and_a_gain_per_change():
    import asyncio

    from conftest import MockLLM
    from test_pipeline_learn import ANALYSIS, EVIDENCE, GOOD_PLAN
    from tailortex.pipeline.tailor import TailorInput, tailor

    llm = MockLLM(ANALYSIS, [GOOD_PLAN])
    r = asyncio.run(tailor(TailorInput(tex=JAKE, jd="Python, Kubernetes, REST APIs", evidence=EVIDENCE, compile_pdf=False), llm))
    assert set(r["ats"]) == {"before", "after"} and r["ats"]["after"] >= r["ats"]["before"]
    assert r["gains"]["gaps"] and all(g["gain"] > 0 for g in r["gains"]["gaps"])
    assert all("gain" in c and "terms" in c for c in r["changes"])
    assert sum(c["gain"] for c in r["changes"]) > 0

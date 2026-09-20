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

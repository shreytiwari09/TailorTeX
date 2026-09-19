"""ATS recommendations: a short, prioritized to-do list built from what a run measured.

Everything here comes from numbers and checks the pipeline already computed on the
PDF's extracted text, so a recommendation never invents a fact about the candidate.
Each item has an action the app can offer:
- fix_source: change something in the LaTeX (formatting, headings, contact line)
- confirm_skill: ask "do you have this?" (adds it to confirmed skills)
- use_context: run again, letting the model use the context entries that back it
- none: advice only
"""

from __future__ import annotations

PRIORITY = {"high": 0, "medium": 1, "low": 2}


def _rec(priority: str, group: str, title: str, detail: str, action: str = "none", term: str | None = None, evidence: list[str] | None = None) -> dict:
    return {"priority": priority, "group": group, "title": title, "detail": detail, "action": action, "term": term, "evidence": evidence or []}


def recommendations(result: dict, evidence_titles: dict[str, str] | None = None) -> list[dict]:
    titles = evidence_titles or {}
    after = result.get("after") or {}
    analysis = result.get("analysis") or {}
    out: list[dict] = []

    # Format: anything that makes the PDF hard for a parser to read comes first.
    for check in after.get("checks") or []:
        if not check.get("ok"):
            out.append(_rec("high", "Format", f"Fix: {check.get('label', 'parse check')}", check.get("detail", ""), "fix_source"))

    pages, limit = after.get("pages"), result.get("page_limit")
    if pages and limit and pages > limit:
        out.append(_rec("high", "Space", f"{pages} pages; the limit is {limit}", "Revert an added bullet, or shorten the longest ones.", "none"))

    # Keywords.
    seen: set[str] = set()
    for kw in result.get("keywords") or []:
        term = kw.get("term", "")
        if not term or term in seen:
            continue
        seen.add(term)
        must = kw.get("must")
        if kw.get("after") == "missing":
            ids = kw.get("evidence_ids") or []
            if ids:
                names = ", ".join(titles.get(i, i) for i in ids[:3])
                out.append(_rec("high" if must else "low", "Keywords", f"Add {term} from your context",
                                f"Backed by {names}, but this version doesn't use it yet.", "use_context", term, ids))
            elif must:
                out.append(_rec("medium", "Keywords", f"Do you have {term}?",
                                "The job requires it and nothing in your resume or context shows it. Confirm only if you could talk about it in an interview.",
                                "confirm_skill", term))
        elif kw.get("after") == "listed" and must:
            out.append(_rec("medium", "Keywords", f"Show {term} in a bullet",
                            "It's only in your Skills list. Recruiters and screeners weigh skills shown in use more.", "use_context", term))
        if kw.get("in_pdf") is False and kw.get("after") != "missing":
            out.append(_rec("high", "Format", f"{term} isn't readable in the PDF",
                            "It's in the source but can't be found in the extracted text. Check fonts and ligatures.", "fix_source", term))

    # Title.
    title_score = after.get("title")
    target = analysis.get("title")
    if target and title_score is not None and title_score < 0.5:
        out.append(_rec("medium", "Title", f"Your titles don't match “{target}”",
                        "If it's true for you, use the target title's words in your summary or headline.", "none"))

    # Space left on the page.
    fill = after.get("page_fill")
    if pages and limit and pages <= limit and fill is not None and fill < 0.7:
        out.append(_rec("low", "Space", f"Room for more: the last page is {round(fill * 100)}% full",
                        "Add one more bullet about your most relevant work.", "use_context"))

    # Context entries that fit the job but weren't used.
    for s in result.get("suggestions") or []:
        if s.get("still_missing") and not s.get("cited"):
            terms = ", ".join(s["still_missing"][:4])
            out.append(_rec("medium" if s.get("must") else "low", "Context", f"Use “{s.get('title') or s.get('id')}”",
                            f"It covers {terms}, which this version doesn't show.", "use_context", None, [s["id"]]))

    out.sort(key=lambda r: PRIORITY[r["priority"]])
    return out

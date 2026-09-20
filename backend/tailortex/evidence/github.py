"""Import public GitHub repos as evidence (public API only, no scraping, no login)."""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from ..types import EvidenceItem

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 5  # up to 500 repos; more than anyone picks from by hand
# Reading one repo costs two API calls (languages and README). Anonymous requests are limited to 60 an hour,
# so importing is capped; set GITHUB_TOKEN on the server to raise the limit to 5000.
MAX_IMPORT = 25
AUTO_IMPORT = 10  # at most this many are imported without asking; above it, the person picks
USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


# GitHub's language stats include build and config files; these aren't resume skills.
_NOT_SKILLS = {"Makefile", "Mako", "Procfile", "Batchfile", "Roff", "Jinja", "Smarty", "Starlark", "Nix", "M4", "Rich Text Format"}
_LANG_NAMES = {"Dockerfile": "Docker", "Jupyter Notebook": "Jupyter", "Vue": "Vue.js", "HCL": "Terraform (HCL)"}


class GitHubError(Exception):
    pass


def _headers(raw: bool = False) -> dict[str, str]:
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json", "User-Agent": "TailorTeX"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code == 404:
        raise GitHubError(f"GitHub {what} not found.")
    if r.status_code in (403, 429):
        raise GitHubError("GitHub's rate limit for anonymous requests was reached. Try again in a while.")
    if r.status_code != 200:
        raise GitHubError(f"GitHub returned an error ({r.status_code}).")


async def list_repos(username: str) -> list[dict]:
    """Every public repo the person owns, newest activity first. Pages through GitHub until they run out."""
    if not USERNAME.match(username):
        raise GitHubError("That doesn't look like a GitHub username.")
    raw: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0) as http:
        for page in range(1, MAX_PAGES + 1):
            try:
                r = await http.get(
                    f"{API}/users/{username}/repos",
                    params={"per_page": PER_PAGE, "page": page, "sort": "pushed", "type": "owner"},
                    headers=_headers(),
                )
            except httpx.HTTPError:
                raise GitHubError("Couldn't reach GitHub.") from None
            _check(r, "user")
            batch = r.json()
            raw += batch
            if len(batch) < PER_PAGE:
                break
    repos = [
        {
            "name": repo["name"],
            "description": repo.get("description") or "",
            "language": repo.get("language"),
            "topics": repo.get("topics") or [],
            "stars": repo.get("stargazers_count", 0),
            "fork": repo.get("fork", False),
            "url": repo.get("html_url"),
            "pushed_at": repo.get("pushed_at"),
        }
        for repo in raw
    ]
    repos.sort(key=lambda x: (x["fork"], -x["stars"], x["pushed_at"] or ""), reverse=False)
    return repos


def rank_repos(repos: list[dict]) -> list[dict]:
    """The person's own work, strongest first: most stars, then most recently worked on."""
    own = [r for r in repos if not r["fork"]] or repos
    own.sort(key=lambda r: r["pushed_at"] or "", reverse=True)
    own.sort(key=lambda r: r["stars"], reverse=True)
    return own


def clean_readme(md: str, limit: int = 900) -> str:
    """The prose of a README: no badges, images, HTML, code blocks, tables or links."""
    t = re.sub(r"```.*?```", " ", md, flags=re.DOTALL)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.DOTALL)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    lines = []
    for line in t.splitlines():
        s = line.strip()
        if not s or s.startswith("|") or s.startswith("#") and len(s) < 4:
            continue
        s = re.sub(r"^#+\s*", "", s)
        s = re.sub(r"^[-*+]\s+", "", s)
        s = re.sub(r"[*_`]+", "", s)
        if len(s) > 2:
            lines.append(s.rstrip(".") + ".")
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


async def all_or_choice(username: str) -> tuple[list[EvidenceItem], list[dict]]:
    """Import every repo when there are few; otherwise return the list so the person picks.

    ([entries], []) when everything was imported, ([], [repos to choose from]) when there are too many.
    """
    own = rank_repos(await list_repos(username))
    if not own:
        raise GitHubError(f"{username} has no public repositories.")
    if len(own) > AUTO_IMPORT:
        return [], own
    return await import_repos(username, [r["name"] for r in own], own), []


async def best_repos(username: str, n: int = AUTO_IMPORT) -> list[EvidenceItem]:
    """A user's strongest public work, imported without asking."""
    own = rank_repos(await list_repos(username))
    if not own:
        raise GitHubError(f"{username} has no public repositories.")
    return await import_repos(username, [r["name"] for r in own[:n]], own)


async def import_repos(username: str, names: list[str], known: list[dict] | None = None) -> list[EvidenceItem]:
    if not USERNAME.match(username):
        raise GitHubError("That doesn't look like a GitHub username.")
    names = [n for n in names if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", n)][:MAX_IMPORT]
    repos = {r["name"]: r for r in (known if known is not None else await list_repos(username))}
    async with httpx.AsyncClient(timeout=20.0) as http:

        async def one(name: str) -> EvidenceItem | None:
            repo = repos.get(name)
            if not repo:
                return None
            langs_r, readme_r = await asyncio.gather(
                http.get(f"{API}/repos/{username}/{name}/languages", headers=_headers()),
                http.get(f"{API}/repos/{username}/{name}/readme", headers=_headers(raw=True)),
                return_exceptions=True,
            )
            langs: list[str] = []
            if isinstance(langs_r, httpx.Response) and langs_r.status_code == 200:
                langs = [_LANG_NAMES.get(lang, lang) for lang in langs_r.json() if lang not in _NOT_SKILLS][:6]
            readme = ""
            if isinstance(readme_r, httpx.Response) and readme_r.status_code == 200:
                readme = clean_readme(readme_r.text)
            skills = list(dict.fromkeys(langs + [t.replace("-", " ") for t in repo["topics"]][:8]))
            text = " ".join(p for p in [repo["description"].rstrip(".") + "." if repo["description"] else "", readme] if p)
            return EvidenceItem(id=f"gh-{name}", source="github", title=name, text=text[:1200], skills=skills, url=repo["url"])

        items = await asyncio.gather(*(one(n) for n in names))
    return [i for i in items if i]

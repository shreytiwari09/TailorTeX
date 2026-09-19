"""Import public GitHub repos as evidence (public API only, no scraping, no login)."""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from ..types import EvidenceItem

API = "https://api.github.com"
USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


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
    if not USERNAME.match(username):
        raise GitHubError("That doesn't look like a GitHub username.")
    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            r = await http.get(f"{API}/users/{username}/repos", params={"per_page": 100, "sort": "pushed", "type": "owner"}, headers=_headers())
        except httpx.HTTPError:
            raise GitHubError("Couldn't reach GitHub.") from None
    _check(r, "user")
    repos = []
    for repo in r.json():
        repos.append({
            "name": repo["name"],
            "description": repo.get("description") or "",
            "language": repo.get("language"),
            "topics": repo.get("topics") or [],
            "stars": repo.get("stargazers_count", 0),
            "fork": repo.get("fork", False),
            "url": repo.get("html_url"),
            "pushed_at": repo.get("pushed_at"),
        })
    repos.sort(key=lambda x: (x["fork"], -x["stars"], x["pushed_at"] or ""), reverse=False)
    return repos


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


async def import_repos(username: str, names: list[str]) -> list[EvidenceItem]:
    if not USERNAME.match(username):
        raise GitHubError("That doesn't look like a GitHub username.")
    names = [n for n in names if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", n)][:8]
    repos = {r["name"]: r for r in await list_repos(username)}
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
                langs = list(langs_r.json().keys())[:6]
            readme = ""
            if isinstance(readme_r, httpx.Response) and readme_r.status_code == 200:
                readme = clean_readme(readme_r.text)
            skills = list(dict.fromkeys(langs + [t.replace("-", " ") for t in repo["topics"]][:8]))
            text = " ".join(p for p in [repo["description"].rstrip(".") + "." if repo["description"] else "", readme] if p)
            return EvidenceItem(id=f"gh-{name}", source="github", title=name, text=text[:1200], skills=skills, url=repo["url"])

        items = await asyncio.gather(*(one(n) for n in names))
    return [i for i in items if i]

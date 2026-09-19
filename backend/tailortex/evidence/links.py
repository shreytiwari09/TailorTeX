"""Recognize the links people paste about themselves: GitHub, LinkedIn, or a portfolio site."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .github import USERNAME

_GITHUB_RESERVED = {
    "orgs", "settings", "topics", "explore", "features", "about", "login", "join", "sponsors", "marketplace",
    "pricing", "enterprise", "collections", "trending", "notifications", "search",
}


def classify(link: str) -> tuple[str, dict[str, str]]:
    """(kind, details): kind is github_user, github_repo, linkedin, portfolio or invalid."""
    raw = link.strip().strip("<>()\"'").rstrip("/.,;")
    if not raw or " " in raw:
        return "invalid", {}
    url = raw if re.match(r"^https?://", raw, re.IGNORECASE) else "https://" + raw
    parts_url = urlparse(url)
    host = (parts_url.hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return "invalid", {}
    parts = [x for x in parts_url.path.split("/") if x]
    if host == "github.com":
        if not parts or parts[0].lower() in _GITHUB_RESERVED or not USERNAME.match(parts[0]):
            return "invalid", {}
        if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", parts[1]):
            return "github_repo", {"user": parts[0], "repo": parts[1].removesuffix(".git"), "url": url}
        return "github_user", {"user": parts[0], "url": url}
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin", {"url": url}
    return "portfolio", {"url": url}


def split_links(text: str) -> list[str]:
    """Links from free text: separated by spaces, commas or new lines."""
    return list(dict.fromkeys(x for x in re.split(r"[\s,;]+", text) if x.strip()))

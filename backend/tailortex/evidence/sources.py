"""Read text from a LinkedIn profile PDF or a portfolio page.

LinkedIn doesn't let apps read profiles from a link, and its terms forbid
scraping, so TailorTeX reads the PDF LinkedIn itself exports ("Save to PDF" on
your profile) or text you paste. Portfolio pages are fetched from the server,
refusing private and internal addresses so the fetch can't be pointed at the
server's own network.
"""

from __future__ import annotations

import asyncio
import csv
import html
import io
import ipaddress
import re
import socket
import zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_PDF_BYTES = 5_000_000
MAX_ZIP_BYTES = 20_000_000
MAX_CSV_BYTES = 10_000_000
MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 30_000


class SourceError(Exception):
    pass


# --- LinkedIn PDF ----------------------------------------------------------------------


def pdf_to_text(data: bytes) -> str:
    if len(data) > MAX_PDF_BYTES:
        raise SourceError("That PDF is larger than 5 MB.")
    if not data.startswith(b"%PDF"):
        raise SourceError("That file isn't a PDF. On your LinkedIn profile, use More → Save to PDF.")
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages[:12]]
    except Exception:  # pypdf raises many kinds of errors on damaged files
        raise SourceError("Couldn't read that PDF.") from None
    text = "\n".join(pages)
    text = re.sub(r"(?m)^\s*Page \d+ of \d+\s*$", "", text)  # LinkedIn's page footers
    return clean_text(text)


# The files read from LinkedIn's data archive. Messages, connections, invitations and
# everything else in the archive are never opened.
ARCHIVE_FILES = {"profile", "positions", "projects", "skills", "shares", "certifications", "honors", "publications"}


def read_linkedin_archive(data: bytes) -> dict[str, list[dict[str, str]]]:
    """Rows of the profile, positions, projects, skills, posts (shares), certifications, honors and publications CSVs."""
    if len(data) > MAX_ZIP_BYTES:
        raise SourceError("That ZIP is larger than 20 MB. In LinkedIn's export, pick only the data you need (posts, profile, positions, projects, skills).")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SourceError("That file isn't a ZIP. Upload the archive LinkedIn emails you.") from None
    out: dict[str, list[dict[str, str]]] = {}
    for info in zf.infolist():
        base = info.filename.rsplit("/", 1)[-1].lower()
        name = base[:-4] if base.endswith(".csv") else ""
        if name not in ARCHIVE_FILES or info.file_size > MAX_CSV_BYTES:
            continue
        raw = zf.read(info).decode("utf-8-sig", errors="replace")
        if raw.lstrip().lower().startswith("notes:"):  # some exports put notes above the header
            raw = raw.split("\n\n", 1)[-1]
        rows = csv.DictReader(io.StringIO(raw))
        out[name] = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in rows]
    if not out:
        raise SourceError("That ZIP doesn't look like a LinkedIn data archive (no Profile, Positions or Shares file in it).")
    return out


def clean_text(text: str) -> str:
    text = text.replace(" ", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


# --- portfolio pages --------------------------------------------------------------------


def _blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified


async def _check_host(host: str, port: int) -> None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceError(f"Couldn't find {host}. Check the address.") from None
    if not infos or any(_blocked_ip(info[4][0]) for info in infos):
        raise SourceError("That address points to a private network, so it can't be read.")


async def fetch_page(url: str) -> tuple[str, str]:
    """(final URL, HTML) for a public web page, following up to 4 redirects safely."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=False, headers={"User-Agent": "TailorTeX/0.1 (+resume tailoring)"}) as http:
        for _ in range(5):
            parts = urlparse(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise SourceError("Use a normal web address, like https://yourname.dev.")
            await _check_host(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
            try:
                async with http.stream("GET", url) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code != 200:
                        raise SourceError(f"The page returned an error ({r.status_code}).")
                    ctype = r.headers.get("content-type", "")
                    if "html" not in ctype and "text" not in ctype:
                        raise SourceError("That address isn't a web page.")
                    body = b""
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_PAGE_BYTES:
                            break
                    return url, body.decode(r.encoding or "utf-8", errors="replace")
            except httpx.HTTPError:
                raise SourceError("Couldn't load that page. Check the address, or paste the text instead.") from None
    raise SourceError("That page redirects too many times.")


class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas"}
    BLOCK = {"p", "div", "section", "article", "li", "ul", "ol", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "header", "footer", "main", "aside"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self.meta: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and a.get("content"):
                self.meta.append(a["content"])
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(page: str) -> str:
    p = _TextParser()
    try:
        p.feed(page)
    except Exception:  # malformed HTML: fall back to a crude strip
        return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", page)))
    head = [p.title.strip()] + list(dict.fromkeys(m.strip() for m in p.meta))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(p.parts).split("\n")]
    body = "\n".join(ln for ln in lines if ln)
    return clean_text("\n".join([h for h in head if h] + [body]))

"""DOIs: recognised strictly, resolved to metadata through Crossref (one fixed host).

A DOI alone doesn't lead to a PDF, so this module only ever fetches *metadata*. What it is
used for:

* a DOI that is really an arXiv paper (``10.48550/arXiv.2310.11511``) is imported in full
  through the arXiv importer;
* for any other DOI, metadata can be applied to a paper the user already uploaded.

Refused entirely in ``LOCAL_ONLY`` mode, like the arXiv importer.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ValidationError
from app.services import arxiv, safe_fetch

API_HOST = "api.crossref.org"
# Crossref's recommended DOI pattern, anchored: nothing outside it ever reaches a URL.
_DOI = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
_PREFIX = re.compile(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)

client_factory: Callable[[], httpx.AsyncClient] = safe_fetch.make_client  # tests replace this


@dataclass
class DoiRecord:
    doi: str
    title: str = ""
    authors: list[dict[str, Any]] = field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    published: str | None = None
    venue: str | None = None


def parse_doi(text: str) -> str:
    """ "doi:10.1000/xyz", "https://doi.org/10.1000/xyz" or "10.1000/xyz" → "10.1000/xyz"."""
    doi = _PREFIX.sub("", text.strip()).strip()
    if not _DOI.match(doi):
        raise ValidationError(
            f"“{text.strip()[:80]}” isn't a DOI.",
            hint="A DOI looks like 10.1145/3292500.3330701 or https://doi.org/10.1145/3292500.3330701.",
        )
    return doi


def is_doi(text: str) -> bool:
    try:
        parse_doi(text)
    except ValidationError:
        return False
    return True


def arxiv_id_of(doi: str) -> str | None:
    """The arXiv id behind a DataCite arXiv DOI, else None."""
    match = _ARXIV_DOI.match(doi)
    return match.group(1) if match else None


def _plain(text: str) -> str:
    """Crossref text fields are HTML-escaped ("Data Mining &amp; Knowledge") and may hold tags."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _title(message: dict[str, Any]) -> str:
    """Crossref keeps a subtitle apart: title "Optuna", subtitle "A Next-generation …"."""
    title = _plain((message.get("title") or [""])[0])
    subtitle = _plain((message.get("subtitle") or [""])[0])
    if title and subtitle and subtitle.lower() not in title.lower():
        separator = " " if title.endswith((":", "?", "!")) else ": "
        return f"{title}{separator}{subtitle}"
    return title


def _clean_abstract(jats: str) -> str:
    text = _plain(jats)  # Crossref abstracts are JATS XML
    return re.sub(r"^abstract[:.]?\s+", "", text, flags=re.IGNORECASE)


def parse_work(payload: bytes, doi: str) -> DoiRecord:
    try:
        message = json.loads(payload)["message"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError("Crossref's answer couldn't be read.") from exc
    parts = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = parts[0] if parts and isinstance(parts[0], int) else None
    published = "-".join(f"{p:02d}" if i else f"{p:04d}" for i, p in enumerate(parts) if p) or None
    authors = []
    for a in message.get("author") or []:
        name = _plain(
            " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name") or ""
        )
        affiliations = [x["name"] for x in a.get("affiliation") or [] if x.get("name")]
        affiliation = affiliations[0] if affiliations else None
        if name.strip():
            authors.append({"name": name, "affiliation": affiliation})
    return DoiRecord(
        doi=str(message.get("DOI") or doi).lower(),
        title=_title(message),
        authors=authors,
        abstract=_clean_abstract(message.get("abstract") or ""),
        year=year,
        published=published,
        venue=_plain((message.get("container-title") or [""])[0]) or None,
    )


async def fetch(settings: Settings, reference: str) -> DoiRecord:
    if settings.local_only:
        raise AppError(
            "Looking up a DOI is turned off.",
            hint="LOCAL_ONLY is on, so nothing is fetched from the internet.",
        )
    doi = parse_doi(reference)
    url = f"https://{API_HOST}/works/{quote(doi, safe='/')}"
    async with client_factory() as client:
        payload = await safe_fetch.get_bytes(
            client,
            url,
            2_000_000,
            {API_HOST},
            not_found="Crossref has no record of this DOI.",
            service="Crossref",
        )
    record = parse_work(payload, doi)
    if not record.title:
        raise ValidationError("Crossref has no title for this DOI.")
    return record


def classify(reference: str) -> tuple[str, str]:
    """("arxiv", ref) or ("doi", doi) — anything else is refused with a hint for both."""
    text = reference.strip()
    if is_doi(text):
        doi = parse_doi(text)
        arxiv_id = arxiv_id_of(doi)
        return ("arxiv", arxiv_id) if arxiv_id else ("doi", doi)
    try:
        arxiv.parse_reference(text)
    except ValidationError:
        raise ValidationError(
            f"“{text[:80]}” isn't an arXiv id, arXiv link or DOI.",
            hint="Use 2310.11511, https://arxiv.org/abs/2310.11511 or 10.1145/3292500.3330701.",
        ) from None
    return "arxiv", text

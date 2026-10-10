"""Import papers from arXiv by id or link: the PDF plus the authoritative title, authors,
abstract and date from arXiv's own API (the parser can only guess these from the PDF).

Only two fixed hosts are ever contacted — nothing the user types becomes a URL — and a
redirect to any other host is refused. Refused entirely in ``LOCAL_ONLY`` mode.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ValidationError
from app.services import safe_fetch

PDF_HOST = "arxiv.org"
API_HOST = "export.arxiv.org"
ALLOWED_HOSTS = {PDF_HOST, API_HOST}
ATOM = "{http://www.w3.org/2005/Atom}"

_NEW_ID = r"\d{4}\.\d{4,5}"
_OLD_ID = r"[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}"
_REF = re.compile(
    rf"^(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:)?(?P<id>{_NEW_ID}|{_OLD_ID})"
    r"(?:v(?P<version>\d+))?(?:\.pdf)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)

# Tests replace this to serve canned responses without the network.
ClientFactory = Callable[[], httpx.AsyncClient]


client_factory: ClientFactory = safe_fetch.make_client


@dataclass
class ArxivPaper:
    arxiv_id: str  # without version
    version: str | None
    pdf: bytes
    title: str = ""
    authors: list[dict[str, Any]] = field(default_factory=list)
    abstract: str = ""
    published: str | None = None  # YYYY-MM-DD
    year: int | None = None
    doi: str | None = None

    @property
    def filename(self) -> str:
        return f"{self.arxiv_id.replace('/', '_')}.pdf"


def parse_reference(text: str) -> tuple[str, str | None]:
    """ "2310.11511", "arXiv:2310.11511v2", "https://arxiv.org/abs/2310.11511" → (id, version)."""
    match = _REF.match(text.strip())
    if match is None:
        raise ValidationError(
            f"“{text.strip()[:80]}” isn't an arXiv id or link.",
            hint="Use an id like 2310.11511 or a link like https://arxiv.org/abs/2310.11511.",
        )
    arxiv_id = match.group("id")
    return (arxiv_id.lower() if "/" in arxiv_id else arxiv_id), match.group("version")


def _text(node: ET.Element | None) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def parse_atom(xml: bytes) -> dict[str, Any]:
    """Title, authors, abstract, date and DOI from arXiv's API answer (one entry)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AppError("arXiv's answer couldn't be read.") from exc
    entry = root.find(f"{ATOM}entry")
    if (
        entry is None
        or entry.find(f"{ATOM}title") is None
        or "/api/errors" in _text(entry.find(f"{ATOM}id"))
    ):
        raise ValidationError("arXiv has no paper with this id.")
    authors = [
        {
            "name": _text(a.find(f"{ATOM}name")),
            "affiliation": _text(a.find("{http://arxiv.org/schemas/atom}affiliation")) or None,
        }
        for a in entry.findall(f"{ATOM}author")
        if _text(a.find(f"{ATOM}name"))
    ]
    published = _text(entry.find(f"{ATOM}published"))[:10] or None
    doi = _text(entry.find("{http://arxiv.org/schemas/atom}doi")) or None
    return {
        "title": _text(entry.find(f"{ATOM}title")),
        "authors": authors,
        "abstract": _text(entry.find(f"{ATOM}summary")),
        "published": published,
        "year": int(published[:4]) if published else None,
        "doi": doi,
    }


async def _get(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
    return await safe_fetch.get_bytes(
        client,
        url,
        limit,
        ALLOWED_HOSTS,
        not_found="arXiv has no paper with this id.",
        service="arXiv",
    )


async def fetch(settings: Settings, reference: str) -> ArxivPaper:
    if settings.local_only:
        raise AppError(
            "Importing from arXiv is turned off.",
            hint="LOCAL_ONLY is on, so nothing is fetched from the internet. Upload the PDF.",
        )
    arxiv_id, version = parse_reference(reference)
    limit = settings.max_upload_size_mb * 1024 * 1024
    suffix = f"v{version}" if version else ""
    async with client_factory() as client:
        meta = parse_atom(
            await _get(client, f"https://{API_HOST}/api/query?id_list={arxiv_id}", 2_000_000)
        )
        pdf = await _get(client, f"https://{PDF_HOST}/pdf/{arxiv_id}{suffix}", limit)
    if not pdf.startswith(b"%PDF"):
        raise AppError("arXiv didn't return a PDF for this paper.")
    return ArxivPaper(arxiv_id=arxiv_id, version=version, pdf=pdf, **meta)

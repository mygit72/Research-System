"""BibTeX and RIS for a set of papers, from their (user-correctable) metadata.

Only what the metadata actually has is written — no invented venues or pages.
arXiv-only papers become `@misc` with `eprint`/`archivePrefix`, which BibLaTeX and
Zotero understand; papers with a venue become `@article`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_BIBTEX_SPECIAL = str.maketrans(
    {"{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}
)


_TITLE_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "on",
        "of",
        "for",
        "in",
        "to",
        "and",
        "with",
        "towards",
        "toward",
        "via",
        "from",
        "by",
        "at",
        "is",
        "are",
    ]
)


@dataclass
class Reference:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _last_name(author: str) -> str:
    author = author.strip()
    if "," in author:  # "Wei, Chen"
        return author.split(",", 1)[0].strip()
    return author.split()[-1] if author.split() else ""


def citation_keys(references: list[Reference]) -> list[str]:
    """wei2023lowrank: first author's last name, year, first significant title word; unique."""
    keys: list[str] = []
    seen: dict[str, int] = {}
    for ref in references:
        last = (
            re.sub(r"[^a-z]", "", _ascii(_last_name(ref.authors[0])).lower()) if ref.authors else ""
        )
        words = [
            word
            for word in (re.sub(r"[^a-z0-9]", "", w) for w in _ascii(ref.title).lower().split())
            if word and word not in _TITLE_STOPWORDS
        ]
        key = f"{last or 'anon'}{ref.year or ''}{words[0] if words else 'paper'}"
        count = seen.get(key, 0)
        seen[key] = count + 1
        keys.append(key if count == 0 else f"{key}{chr(ord('a') + count)}")
    return keys


def bibtex(references: list[Reference]) -> str:
    entries = []
    for key, ref in zip(citation_keys(references), references, strict=True):
        kind = "article" if ref.venue and not _is_arxiv_venue(ref.venue) else "misc"
        fields: list[tuple[str, str]] = [("title", f"{{{ref.title.translate(_BIBTEX_SPECIAL)}}}")]
        if ref.authors:
            fields.append(
                ("author", " and ".join(a.translate(_BIBTEX_SPECIAL) for a in ref.authors))
            )
        if ref.year:
            fields.append(("year", str(ref.year)))
        if kind == "article" and ref.venue:
            fields.append(("journal", ref.venue.translate(_BIBTEX_SPECIAL)))
        if ref.doi:
            fields.append(("doi", ref.doi))
        if ref.arxiv_id:
            fields += [("eprint", ref.arxiv_id), ("archivePrefix", "arXiv")]
        if ref.keywords:
            fields.append(
                ("keywords", ", ".join(k.translate(_BIBTEX_SPECIAL) for k in ref.keywords))
            )
        body = ",\n".join(
            f"  {name} = {value if value.startswith('{') else '{' + value + '}'}"
            for name, value in fields
        )
        entries.append(f"@{kind}{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def ris(references: list[Reference]) -> str:
    records = []
    for ref in references:
        kind = "JOUR" if ref.venue and not _is_arxiv_venue(ref.venue) else "GEN"
        lines = [f"TY  - {kind}", f"TI  - {ref.title}"]
        lines += [f"AU  - {author}" for author in ref.authors]
        if ref.year:
            lines.append(f"PY  - {ref.year}")
        if kind == "JOUR" and ref.venue:
            lines.append(f"JO  - {ref.venue}")
        if ref.doi:
            lines.append(f"DO  - {ref.doi}")
        if ref.arxiv_id:
            lines.append(f"UR  - https://arxiv.org/abs/{ref.arxiv_id}")
        lines += [f"KW  - {keyword}" for keyword in ref.keywords]
        if ref.abstract:
            lines.append(f"AB  - {' '.join(ref.abstract.split())}")
        lines.append("ER  - ")
        records.append("\r\n".join(lines))
    return "\r\n".join(records) + ("\r\n" if records else "")


def _is_arxiv_venue(venue: str) -> bool:
    return venue.strip().lower() in {"arxiv", "arxiv preprint", "preprint"}

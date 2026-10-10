"""Deterministic metadata extraction.

Rules and regexes, not an LLM: the fields have strong surface patterns (DOIs,
arXiv IDs, "Abstract", title = largest type on page 1), heuristics are fast and
explainable, and every field records where it came from so the UI can show
confidence and users can correct it. Entity fields (datasets, models, metrics,
tasks) are extracted in Phase 10.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.services.ingestion.cleaning import clean_text
from app.services.ingestion.structure import HeadingDetector
from app.services.ingestion.types import (
    BlockKind,
    DocumentFormat,
    DocumentStructure,
    ExtractedMetadata,
    RawDocument,
    SectionKind,
)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;)\]])", re.I)
ARXIV_NEW_RE = re.compile(r"arxiv[:\s]*(\d{4}\.\d{4,5})(v\d+)?", re.I)
ARXIV_STAMP_RE = re.compile(
    r"arxiv:(\d{4}\.\d{4,5})(v\d+)?\s*\[([a-z\-]+(?:\.[A-Za-z]+)?)\]\s*(\d{1,2}\s+\w{3}\s+\d{4})?",
    re.I,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
KEYWORDS_RE = re.compile(r"^(keywords|key words|index terms)\s*[:—–\-.]\s*(.+)$", re.I)
AFFILIATION_HINT = re.compile(
    r"universit|institut|college|school|department|dept\.|laborator|\blab\b|research|"
    r"academy|centre|center|inc\.|ltd|corporation|google|microsoft|meta|openai|deepmind|"
    r"anthropic|nvidia|amazon|ibm|hospital|faculty",
    re.I,
)
VENUES = [
    "NeurIPS", "NIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL", "EACL", "COLING", "TACL",
    "CVPR", "ICCV", "ECCV", "WACV", "AAAI", "IJCAI", "KDD", "SIGIR", "WWW", "WSDM", "CIKM",
    "RecSys", "UAI", "AISTATS", "COLT", "CoRL", "ICRA", "IROS", "JMLR", "TMLR", "TPAMI",
    "Nature", "Science", "PNAS",
]  # fmt: skip
# Bare names like "Science" appear in affiliations, so a venue needs a year next to it.
VENUE_RE = re.compile(
    r"(Proceedings of [^.\n]{5,120}|Published as a conference paper at [A-Za-z]+ \d{4}|"
    r"\b(?:" + "|".join(VENUES) + r")\s*['’]?\s*(?:19|20)?\d{2}\b)"
)
ARXIV_AREAS = {
    "cs.CL": "Natural Language Processing",
    "cs.CV": "Computer Vision",
    "cs.LG": "Machine Learning",
    "stat.ML": "Machine Learning",
    "cs.AI": "Artificial Intelligence",
    "cs.IR": "Information Retrieval",
    "cs.RO": "Robotics",
    "cs.NE": "Neural and Evolutionary Computing",
    "cs.CR": "Security and Cryptography",
    "cs.SE": "Software Engineering",
    "cs.DB": "Databases",
    "cs.HC": "Human-Computer Interaction",
    "eess.AS": "Audio and Speech Processing",
    "eess.IV": "Image and Video Processing",
    "q-bio": "Quantitative Biology",
    "physics": "Physics",
    "math": "Mathematics",
}
_BAD_EMBEDDED_TITLES = re.compile(
    r"^(untitled|microsoft word|document\d*|slide \d+)|\.(docx?|tex|pdf)$", re.I
)


def _set(meta: ExtractedMetadata, field: str, value: object, source: str, confidence: str) -> None:
    if value in (None, "", []):
        return
    setattr(meta, field, value)
    meta.provenance[field] = {"source": source, "confidence": confidence}


def extract_metadata(
    raw: RawDocument, structure: DocumentStructure, filename: str
) -> ExtractedMetadata:
    meta = ExtractedMetadata()
    embedded = raw.embedded_metadata
    first_pages_text = _front_text(structure)

    # --- identifiers ------------------------------------------------------------------
    stamp = embedded.get("arxiv_stamp", "")
    stamp_match = ARXIV_STAMP_RE.search(stamp) if stamp else None
    if stamp_match:
        _set(meta, "arxiv_id", stamp_match.group(1), "arxiv_stamp", "high")
        area = _arxiv_area(stamp_match.group(3))
        _set(meta, "research_area", area, "arxiv_stamp", "high")
        if stamp_match.group(4):
            try:
                date = datetime.strptime(stamp_match.group(4), "%d %b %Y").date()
                _set(meta, "publication_date", date.isoformat(), "arxiv_stamp", "medium")
            except ValueError:
                pass
    elif m := ARXIV_NEW_RE.search(first_pages_text):
        _set(meta, "arxiv_id", m.group(1), "text", "medium")

    doi = embedded.get("citation_doi") or embedded.get("doi")
    if doi:
        _set(meta, "doi", doi.removeprefix("https://doi.org/"), "embedded", "high")
    elif m := DOI_RE.search(first_pages_text):
        _set(meta, "doi", m.group(1).rstrip("."), "text", "medium")

    # --- title --------------------------------------------------------------------------
    _extract_title(meta, raw, structure, filename)

    # --- authors & affiliations ------------------------------------------------------------
    citation_authors = embedded.get("citation_authors")
    if citation_authors:
        authors = [
            {"name": a.strip(), "affiliation": None, "email": None}
            for a in citation_authors.split(";")
            if a.strip()
        ]
        _set(meta, "authors", authors, "embedded", "high")
    else:
        _extract_people(meta, structure)
    if not meta.authors and (author := embedded.get("author")):
        names = [n.strip() for n in re.split(r";|,| and ", author) if len(n.strip()) > 2]
        _set(
            meta,
            "authors",
            [{"name": n, "affiliation": None, "email": None} for n in names],
            "embedded",
            "medium",
        )

    # --- abstract ---------------------------------------------------------------------
    _extract_abstract(meta, structure, embedded)

    # --- year, venue, keywords -----------------------------------------------------------
    _extract_year(meta, embedded, first_pages_text, raw.format)
    venue = embedded.get("citation_journal_title") or embedded.get("citation_conference_title")
    if venue:
        _set(meta, "venue", venue, "embedded", "high")
    elif m := VENUE_RE.search(first_pages_text[:6000]):
        text = re.sub(r"^Published as a conference paper at ", "", m.group(1)).strip(" ,.")
        _set(meta, "venue", text, "text", "medium")
    elif meta.arxiv_id:
        _set(meta, "venue", "arXiv", "arxiv_id", "medium")

    keywords_line = next(
        (
            KEYWORDS_RE.match(p.text)
            for s in structure.sections[:4]
            for p in s.paragraphs
            if KEYWORDS_RE.match(p.text)
        ),
        None,
    )
    if keywords_line:
        keywords = [
            k.strip(" .")
            for k in re.split(r"[;,·•]", keywords_line.group(2))
            if 1 < len(k.strip()) < 60
        ]
        _set(meta, "keywords", keywords[:15], "text", "high")
    elif embedded.get("keywords"):
        keywords = [k.strip() for k in re.split(r"[;,]", embedded["keywords"]) if k.strip()]
        _set(meta, "keywords", keywords[:15], "embedded", "medium")
    return meta


def _front_text(structure: DocumentStructure) -> str:
    """Text of the first two pages, excluding the references section."""
    end = structure.page_spans.get(2, structure.page_spans.get(1, (0, 0)))[1]
    refs = [s.char_start for s in structure.all_sections() if s.kind == SectionKind.REFERENCES]
    if refs:
        end = min(end, refs[0])
    return structure.full_text[: max(end, 2000) if not refs else end]


def _arxiv_area(category: str) -> str | None:
    if category in ARXIV_AREAS:
        return ARXIV_AREAS[category]
    return ARXIV_AREAS.get(category.split(".")[0])


def _extract_title(
    meta: ExtractedMetadata, raw: RawDocument, structure: DocumentStructure, filename: str
) -> None:
    embedded_title = raw.embedded_metadata.get("citation_title") or raw.embedded_metadata.get(
        "title"
    )
    if raw.format == DocumentFormat.PDF:
        title_block = HeadingDetector(raw).title_block
        if title_block is not None:
            # Titles often wrap into two same-size blocks; join adjacent ones.
            parts = [
                b.text
                for b in raw.blocks
                if b.page == 1
                and b.font_size
                and abs(b.font_size - (title_block.font_size or 0)) < 0.6
                and b.bbox
                and title_block.bbox
                and abs(b.bbox[1] - title_block.bbox[1]) < 80
            ]
            _set(meta, "title", clean_text(" ".join(parts))[:500], "layout", "high")
            return
    # Only a real title heading counts (DOCX "Title" style, or a lone top-level `# Title`).
    title_index = HeadingDetector(raw).explicit_title_index()
    heading_title = next(
        (b.text for b in raw.blocks if b.kind == BlockKind.HEADING and b.heading_level == 0),
        raw.blocks[title_index].text if title_index is not None else None,
    )
    if (
        embedded_title
        and not _BAD_EMBEDDED_TITLES.search(embedded_title.strip())
        and len(embedded_title) > 5
    ):
        _set(meta, "title", clean_text(embedded_title)[:500], "embedded", "medium")
    elif heading_title and raw.format != DocumentFormat.PDF:
        _set(meta, "title", heading_title[:500], "heading", "medium")
    elif structure.sections and structure.sections[0].kind == SectionKind.PREAMBLE:
        first = structure.sections[0].paragraphs[0].text
        if len(first) < 250:
            _set(meta, "title", first, "first_line", "low")
    if not meta.title:
        _set(
            meta,
            "title",
            Path(filename).stem.replace("_", " ").strip() or "Untitled",
            "filename",
            "low",
        )


def _extract_people(meta: ExtractedMetadata, structure: DocumentStructure) -> None:
    if not structure.sections or structure.sections[0].kind != SectionKind.PREAMBLE:
        return
    lines = [p.text for p in structure.sections[0].paragraphs if p.text != meta.title][:12]
    authors: list[dict[str, str | None]] = []
    affiliations: list[str] = []
    emails: list[str] = []
    for line in lines:
        if KEYWORDS_RE.match(line) or line.lower().startswith("abstract") or len(line) > 400:
            break
        emails.extend(EMAIL_RE.findall(line))
        stripped = EMAIL_RE.sub("", line)
        if AFFILIATION_HINT.search(stripped):
            affiliations.append(stripped.strip(" ,;{}"))
            continue
        for name in _split_names(stripped):
            authors.append({"name": name, "affiliation": None, "email": None})
    for author, email in zip(authors, emails, strict=False):
        author["email"] = email
    if len(affiliations) == 1:
        for author in authors:
            author["affiliation"] = affiliations[0]
    _set(meta, "authors", authors[:50], "layout", "medium")
    _set(meta, "affiliations", list(dict.fromkeys(affiliations))[:20], "layout", "medium")


_NAME_RE = re.compile(r"^[A-Z][\w'’\-]*\.?(?:\s+[A-Z][\w'’\-]*\.?){1,3}$", re.UNICODE)


def _split_names(line: str) -> list[str]:
    line = re.sub(r"[\d∗*†‡§¶#]+", " ", line)  # affiliation markers
    candidates = re.split(r",|;|\band\b|&|\s{3,}", line)
    names = []
    for candidate in candidates:
        name = re.sub(r"\s+", " ", candidate).strip(" .")
        if _NAME_RE.match(name) and 4 <= len(name) <= 60:
            names.append(name)
    return names


def _extract_abstract(
    meta: ExtractedMetadata, structure: DocumentStructure, embedded: dict[str, str]
) -> None:
    for section in structure.all_sections():
        if section.kind == SectionKind.ABSTRACT and section.paragraphs:
            text = " ".join(
                p.text
                for p in section.paragraphs
                if p.kind == BlockKind.TEXT and not KEYWORDS_RE.match(p.text)
            )
            _set(meta, "abstract", text[:5000], "section", "high")
            return
    for section in structure.sections[:2]:
        for paragraph in section.paragraphs:
            m = re.match(r"^abstract\s*[:.—–\-]?\s*(.{80,})", paragraph.text, re.I | re.S)
            if m:
                _set(meta, "abstract", m.group(1)[:5000], "text", "high")
                return
    if description := embedded.get("description"):
        _set(meta, "abstract", description[:5000], "embedded", "low")


def _extract_year(
    meta: ExtractedMetadata, embedded: dict[str, str], front: str, fmt: DocumentFormat
) -> None:
    this_year = datetime.now(UTC).year
    if meta.publication_date:
        _set(
            meta,
            "year",
            int(meta.publication_date[:4]),
            meta.provenance["publication_date"]["source"],
            "high",
        )
        return
    if meta.arxiv_id:
        yymm = meta.arxiv_id.split(".")[0]
        _set(meta, "year", 2000 + int(yymm[:2]), "arxiv_id", "high")
        return
    pub = embedded.get("citation_publication_date")
    if pub and (m := YEAR_RE.search(pub)):
        _set(meta, "year", int(m.group(1)), "embedded", "high")
        _set(meta, "publication_date", pub, "embedded", "high")
        return
    years = [int(y) for y in YEAR_RE.findall(front[:4000]) if int(y) <= this_year + 1]
    if years:
        _set(meta, "year", max(years), "text", "low")
        return
    if fmt != DocumentFormat.PDF:  # DOCX templates carry meaningless creation dates
        return
    created = embedded.get("creationDate", "")
    if m := re.search(r"(19|20)\d{2}", created):
        _set(meta, "year", int(m.group(0)), "file_metadata", "low")

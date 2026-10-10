"""A read-only snapshot of a user's library for the knowledge views.

Built from the database in a handful of queries and cached per user until anything
it depends on changes (papers, metadata, entity links, topic clusterings):

- **papers** with display metadata;
- **authors**, normalized ("Jacob Devlin" = "J. Devlin" when that is unambiguous in the
  library) and filtered ("Language Understanding" parsed off a title line is not a
  person); **institutions** from affiliations;
- **citations among the user's papers**: each parsed reference is matched to a library
  paper by DOI, then arXiv id, then title (exact, or the library title contained in the
  reference text);
- **entity links** and the latest **topic clustering**.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentReference,
    DocumentStatus,
)
from app.models.knowledge import DocumentEntity, Entity, EntityExtraction, TopicClustering
from app.services.ingestion.cleaning import normalize_title


@dataclass
class Paper:
    id: uuid.UUID
    version_id: uuid.UUID
    title: str
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    authors: list[str]  # author keys, in paper order
    institutions: list[str]  # institution keys
    keywords: list[str]
    abstract: str | None
    normalized_title: str
    authors_display: str
    index_status: str


@dataclass
class Author:
    key: str
    name: str
    papers: list[uuid.UUID] = field(default_factory=list)
    institutions: set[str] = field(default_factory=set)
    spellings: set[str] = field(default_factory=set)


@dataclass
class Institution:
    key: str
    name: str
    papers: set[uuid.UUID] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)


@dataclass
class Citation:
    citing: uuid.UUID
    cited: uuid.UUID
    match: str  # doi | arxiv | title
    reference: str


@dataclass
class EntityInfo:
    id: uuid.UUID
    type: str
    name: str
    aliases: list[str]
    info: dict[str, str]
    source: str


@dataclass
class Link:
    document_id: uuid.UUID
    entity_id: uuid.UUID
    relation: str
    mentions: int
    score: float
    variants: list[str]
    evidence: list[dict[str, Any]]


@dataclass
class Library:
    user_id: uuid.UUID
    papers: dict[uuid.UUID, Paper]
    authors: dict[str, Author]
    institutions: dict[str, Institution]
    citations: list[Citation]
    entities: dict[uuid.UUID, EntityInfo]
    links: list[Link]
    topics: dict[uuid.UUID, dict[str, Any]]  # document id → {id, name}
    topic_run: dict[str, Any] | None
    fingerprint: str

    def links_of(self, document_id: uuid.UUID) -> list[Link]:
        return [link for link in self.links if link.document_id == document_id]

    def papers_of_entity(self, entity_id: uuid.UUID) -> list[Link]:
        return [link for link in self.links if link.entity_id == entity_id]


# --- names ---------------------------------------------------------------------------------------

_NOT_A_PERSON = frozenset(
    """university department institute laboratory lab labs research inc corp corporation
    school college faculty center centre abstract introduction google microsoft facebook
    meta openai deepmind amazon ibm nvidia equal contribution correspondence work done
    models model learning language network networks""".split()  # noqa: SIM905
)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def person_key(name: str) -> str:
    tokens = re.sub(r"[^a-z\s'\-]", " ", _ascii(name).lower().replace(".", ". ")).split()
    return " ".join(tokens)


def plausible_author(name: str, title: str) -> bool:
    """Reject strings the PDF metadata parser mistook for authors (title continuations,
    affiliations). Only used for the knowledge views; the paper's metadata is untouched."""
    words = name.replace(".", ". ").split()
    if not 2 <= len(words) <= 5 or any(c.isdigit() for c in name):
        return False
    lowered = {w.strip(".,").lower() for w in words}
    if lowered & _NOT_A_PERSON:
        return False
    title_words = {w.lower() for w in re.findall(r"[A-Za-z]+", title)}
    parts = [p for p in re.findall(r"[A-Za-z]+", name) if len(p) > 1]
    if parts and all(p.lower() in title_words for p in parts):
        return False  # "Language Understanding", "Knowledge-Intensive NLP Tasks": title lines
    if any(p.isupper() and len(p) >= 3 for p in parts):
        return False  # "GUAGE MODELS", "NLP": capitals don't occur in personal names
    return all(
        w[0].isupper() or w.lower() in {"van", "von", "de", "der", "da", "di", "le", "la"}
        for w in words
    )


def merge_initials(keys: list[str]) -> dict[str, str]:
    """Map "j. devlin" → "jacob devlin" when exactly one full first name shares
    surname + initial in the library."""
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key in keys:
        parts = key.split()
        if len(parts) >= 2:
            groups[(parts[-1], parts[0][0])].add(key)
    mapping: dict[str, str] = {}
    for variants in groups.values():
        full = [k for k in variants if len(k.split()[0].rstrip(".")) > 1]
        if len(full) == 1:
            for k in variants:
                if k != full[0] and len(k.split()[0].rstrip(".")) == 1:
                    mapping[k] = full[0]
    return mapping


_EMAILS = re.compile(r"\{[^}]*\}\s*@\S+|\S+@\S+")
_AFFILIATION_SPLIT = re.compile(r"[†‡§¶*∗;]|\s{2,}|\b\d\s+(?=[A-Z])")


def split_affiliation(text: str) -> list[str]:
    """One parsed affiliation line can hold several institutions and the authors' e-mails:
    "Facebook AI †University of Washington ‡Princeton University {vladk, plewis}@fb.com"."""
    parts = []
    for part in _AFFILIATION_SPLIT.split(_EMAILS.sub(" ", text)):
        part = part.strip(" ,.:-\t")
        if 4 <= len(part) <= 100 and part[0].isupper() and any(c.isalpha() for c in part):
            parts.append(part)
    return parts


def institution_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _ascii(name).lower())).strip()


# --- citations -----------------------------------------------------------------------------------

_ARXIV_VERSION = re.compile(r"v\d+$")


def _norm_arxiv(value: str | None) -> str | None:
    return _ARXIV_VERSION.sub("", value.strip().lower()) if value else None


def match_citations(
    papers: dict[uuid.UUID, Paper], references: dict[uuid.UUID, list[DocumentReference]]
) -> list[Citation]:
    by_doi = {p.doi.lower(): p.id for p in papers.values() if p.doi}
    by_arxiv = {a: p.id for p in papers.values() if (a := _norm_arxiv(p.arxiv_id))}
    by_title = {p.normalized_title: p.id for p in papers.values() if len(p.normalized_title) > 12}
    found: dict[tuple[uuid.UUID, uuid.UUID], Citation] = {}
    for citing, refs in references.items():
        for ref in refs:
            target, how = None, ""
            if ref.doi and ref.doi.lower() in by_doi:
                target, how = by_doi[ref.doi.lower()], "doi"
            elif (a := _norm_arxiv(ref.arxiv_id)) and a in by_arxiv:
                target, how = by_arxiv[a], "arxiv"
            else:
                ref_title = normalize_title(ref.title or "")
                if ref_title in by_title:
                    target, how = by_title[ref_title], "title"
                else:
                    raw = normalize_title(ref.raw_text)
                    for title, doc_id in by_title.items():
                        # Long, specific titles only: "attention is all you need" yes, "bert" no.
                        if len(title.split()) >= 4 and f" {title}" in f" {raw}":
                            target, how = doc_id, "title"
                            break
            if target is not None and target != citing:
                found.setdefault((citing, target), Citation(citing, target, how, ref.raw_text))
    return list(found.values())


# --- snapshot ------------------------------------------------------------------------------------

_cache: dict[uuid.UUID, Library] = {}


async def library_fingerprint(session: AsyncSession, user_id: uuid.UUID) -> str:
    docs = (
        await session.execute(
            select(func.count(), func.max(Document.updated_at)).where(Document.user_id == user_id)
        )
    ).one()
    meta = (
        await session.execute(
            select(func.max(DocumentMetadata.updated_at)).where(DocumentMetadata.user_id == user_id)
        )
    ).scalar_one()
    extraction = (
        await session.execute(
            select(func.count(), func.max(EntityExtraction.matched_at)).where(
                EntityExtraction.user_id == user_id
            )
        )
    ).one()
    topics = (
        await session.execute(
            select(func.count(), func.max(TopicClustering.updated_at)).where(
                TopicClustering.user_id == user_id
            )
        )
    ).one()
    return "|".join(str(v) for v in (*docs, meta, *extraction, *topics))


async def load_library(session: AsyncSession, user_id: uuid.UUID) -> Library:
    fingerprint = await library_fingerprint(session, user_id)
    cached = _cache.get(user_id)
    if cached is not None and cached.fingerprint == fingerprint:
        return cached
    library = await _build(session, user_id, fingerprint)
    _cache[user_id] = library
    if len(_cache) > 64:  # bounded: drop the oldest entry
        _cache.pop(next(iter(_cache)))
    return library


async def _build(session: AsyncSession, user_id: uuid.UUID, fingerprint: str) -> Library:
    rows = (
        await session.execute(
            select(Document, DocumentMetadata)
            .outerjoin(DocumentMetadata, DocumentMetadata.version_id == Document.current_version_id)
            .where(
                Document.user_id == user_id,
                Document.status == DocumentStatus.READY,
                Document.current_version_id.is_not(None),
            )
            .order_by(Document.created_at)
        )
    ).all()
    papers: dict[uuid.UUID, Paper] = {}
    raw_authors: list[tuple[uuid.UUID, str, str, str | None]] = []  # (doc, key, name, affiliation)
    raw_affiliations: dict[uuid.UUID, list[str]] = {}
    for doc, meta in rows:
        assert doc.current_version_id is not None
        for listed in meta.authors if meta else []:
            name = (listed.get("name") or "").strip()
            if name and plausible_author(name, doc.title):
                raw_authors.append((doc.id, person_key(name), name, listed.get("affiliation")))
        raw_affiliations[doc.id] = list(meta.affiliations) if meta else []
        papers[doc.id] = Paper(
            id=doc.id,
            version_id=doc.current_version_id,
            title=doc.title,
            year=doc.year,
            venue=meta.venue if meta else None,
            doi=meta.doi if meta else None,
            arxiv_id=meta.arxiv_id if meta else None,
            authors=[],
            institutions=[],
            keywords=list(meta.keywords) if meta else [],
            abstract=meta.abstract if meta else None,
            normalized_title=normalize_title(doc.title),
            authors_display=doc.authors_display,
            index_status=doc.index_status,
        )

    # Authors (with initials merged) and institutions.
    mapping = merge_initials(list({key for _, key, _, _ in raw_authors}))
    authors: dict[str, Author] = {}
    institutions: dict[str, Institution] = {}

    def institution(name: str) -> str | None:
        key = institution_key(name)
        if len(key) < 3:
            return None
        inst = institutions.setdefault(key, Institution(key, name.strip()))
        return inst.key

    for doc_id, key, name, affiliation in raw_authors:
        key = mapping.get(key, key)
        author = authors.setdefault(key, Author(key, name))
        if len(name) > len(author.name):
            author.name = name  # the most complete spelling ("Jacob Devlin" over "J. Devlin")
        author.spellings.add(name)
        if doc_id not in author.papers:
            author.papers.append(doc_id)
            papers[doc_id].authors.append(key)
        affiliations = [affiliation] if affiliation else []
        if not affiliations and len(raw_affiliations.get(doc_id, [])) == 1:
            affiliations = raw_affiliations[doc_id]
        for aff in (part for line in affiliations for part in split_affiliation(line)):
            inst_key = institution(aff)
            if inst_key:
                author.institutions.add(inst_key)
                institutions[inst_key].authors.add(key)
                institutions[inst_key].papers.add(doc_id)
    for doc_id, affiliations in raw_affiliations.items():
        for aff in (part for line in affiliations for part in split_affiliation(line)):
            inst_key = institution(aff)
            if inst_key:
                institutions[inst_key].papers.add(doc_id)
                if inst_key not in papers[doc_id].institutions:
                    papers[doc_id].institutions.append(inst_key)

    # In-library citations.
    references: dict[uuid.UUID, list[DocumentReference]] = defaultdict(list)
    version_doc = {p.version_id: p.id for p in papers.values()}
    if version_doc:
        for ref in (
            await session.execute(
                select(DocumentReference).where(DocumentReference.version_id.in_(list(version_doc)))
            )
        ).scalars():
            references[version_doc[ref.version_id]].append(ref)
    citations = match_citations(papers, references)

    # Entities.
    entities = {
        e.id: EntityInfo(e.id, e.type, e.name, list(e.aliases), dict(e.info), e.source)
        for e in (await session.execute(select(Entity).where(Entity.user_id == user_id))).scalars()
    }
    links = [
        Link(
            row.document_id,
            row.entity_id,
            row.relation,
            row.mentions,
            row.score,
            list(row.variants),
            list(row.evidence),
        )
        for row in (
            await session.execute(
                select(DocumentEntity).where(
                    DocumentEntity.user_id == user_id,
                    DocumentEntity.version_id.in_(list(version_doc) or [uuid.uuid4()]),
                )
            )
        ).scalars()
        if row.entity_id in entities
    ]

    # Topics from the latest clustering.
    run = (
        await session.execute(
            select(TopicClustering)
            .where(TopicClustering.user_id == user_id)
            .order_by(TopicClustering.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    topics: dict[uuid.UUID, dict[str, Any]] = {}
    topic_run = None
    if run is not None:
        topic_run = {
            "id": str(run.id),
            "method": run.method,
            "clusters": run.result.get("clusters", []),
        }
        for cluster in run.result.get("clusters", []):
            for doc_id in cluster["document_ids"]:
                did = uuid.UUID(doc_id)
                if did in papers:
                    topics[did] = {"id": cluster["id"], "name": cluster["name"]}

    return Library(
        user_id=user_id,
        papers=papers,
        authors=authors,
        institutions=institutions,
        citations=citations,
        entities=entities,
        links=links,
        topics=topics,
        topic_run=topic_run,
        fingerprint=fingerprint,
    )

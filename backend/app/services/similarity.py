"""Similar papers: nearest neighbours of a paper-level embedding, with reasons.

The paper vector embeds title + abstract + keywords. Reasons are computed from
the metadata that actually overlaps (shared keywords, distinctive shared terms,
same research area / venue / authors) so every explanation is checkable.
"""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import Document, DocumentMetadata, DocumentVersion, IndexStatus
from app.services.vectorstore import VectorFilter, collection_name, get_vector_store

_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_STOP = frozenset(
    """about above after again against also among another based been before being
    below between both could does doing during each either every from further
    have having here into itself just more most much must never only
    other over same should show shows since some such than that their
    them then there these they this those through thus under until using
    very were what when where which while will with within without would
    paper propose proposed approach method methods results result study work task tasks
    model models data dataset datasets performance improve improves improved new first
    second""".split()  # noqa: SIM905
)


@dataclass
class SimilarPaper:
    document_id: uuid.UUID
    score: float
    reasons: list[str]


def _terms(meta: DocumentMetadata | None, title: str) -> Counter[str]:
    text = " ".join([title, (meta.abstract or "") if meta else ""]).lower()
    return Counter(w for w in _WORD.findall(text) if w not in _STOP)


def explain(
    base: DocumentMetadata | None,
    base_title: str,
    other: DocumentMetadata | None,
    other_title: str,
    document_frequency: Counter[str],
    library_size: int,
) -> list[str]:
    reasons: list[str] = []
    if base and other:
        shared_keywords = {k.lower() for k in base.keywords} & {k.lower() for k in other.keywords}
        if shared_keywords:
            reasons.append("Shared keywords: " + ", ".join(sorted(shared_keywords)[:4]))
        if base.research_area and base.research_area == other.research_area:
            reasons.append(f"Same research area ({base.research_area})")
        if base.venue and other.venue and base.venue.lower() == other.venue.lower():
            reasons.append(f"Same venue ({base.venue})")
        base_authors = {a.get("name", "").lower() for a in base.authors}
        common = [a["name"] for a in other.authors if a.get("name", "").lower() in base_authors]
        if common:
            reasons.append("Shared authors: " + ", ".join(common[:3]))
    a, b = _terms(base, base_title), _terms(other, other_title)

    def idf(term: str) -> float:
        return math.log((1 + library_size) / (1 + document_frequency[term]))

    # Rank shared terms by rarity in the library (IDF) so generic words don't dominate.
    shared = sorted(
        set(a) & set(b),
        key=lambda t: (
            -(min(a[t], b[t]) * math.log((1 + library_size) / (1 + document_frequency[t])))
        ),
    )
    if shared:
        reasons.append("Both discuss " + ", ".join(shared[:4]))
    return reasons


async def similar_documents(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    document: Document,
    limit: int = 6,
) -> tuple[str, list[SimilarPaper]]:
    """Returns (status, results). Status explains empty results ("not_indexed", ...)."""
    if document.index_status != IndexStatus.INDEXED or document.current_version_id is None:
        return "not_indexed", []
    version = await session.get(DocumentVersion, document.current_version_id)
    if version is None or not version.embedding_model or not version.embedding_dimension:
        return "not_indexed", []
    name = collection_name("documents", version.embedding_model, version.embedding_dimension)
    store = get_vector_store(settings)

    def query() -> list[tuple[uuid.UUID, float]]:
        vector = store.get_vector(name, document.id)
        if vector is None:
            return []
        hits = store.search(
            name, vector, VectorFilter(user_id=user_id, exclude_document_ids=[document.id]), limit
        )
        return [(hit.id, hit.score) for hit in hits]

    hits = await asyncio.to_thread(query)
    if not hits:
        return "no_other_papers", []

    user_cond = (
        or_(Document.user_id == user_id, Document.user_id == settings.demo_user_id)
        if settings.demo_mode
        else (Document.user_id == user_id)
    )
    ids = [document.id, *(doc_id for doc_id, _ in hits)]
    rows = await session.execute(
        select(Document, DocumentMetadata)
        .outerjoin(DocumentMetadata, DocumentMetadata.version_id == Document.current_version_id)
        .where(Document.id.in_(ids), user_cond)
    )
    by_id = {doc.id: (doc, meta) for doc, meta in rows.all()}
    all_meta = await session.execute(
        select(Document.title, DocumentMetadata)
        .outerjoin(DocumentMetadata, DocumentMetadata.version_id == Document.current_version_id)
        .where(user_cond)
    )
    library = [(title, meta) for title, meta in all_meta.all()]
    document_frequency: Counter[str] = Counter()
    for title, meta in library:
        document_frequency.update(set(_terms(meta, title)))

    base_doc, base_meta = by_id[document.id]
    results = []
    for doc_id, score in hits:
        if doc_id not in by_id:
            continue  # stale vector for a deleted paper
        other_doc, other_meta = by_id[doc_id]
        results.append(
            SimilarPaper(
                document_id=doc_id,
                score=round(score, 4),
                reasons=explain(
                    base_meta,
                    base_doc.title,
                    other_meta,
                    other_doc.title,
                    document_frequency,
                    len(library),
                ),
            )
        )
    return "ok", results

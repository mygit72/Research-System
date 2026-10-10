"""Keeping a user's entity links up to date, incrementally.

`ensure_entities()` is cheap when nothing changed (two small queries) and is called
after a paper is processed and before any knowledge read (graph, entity pages,
timeline). It:

1. runs discovery for current versions that have none yet (or whose title or the
   extractor version changed);
2. builds the library dictionary (catalog + every discovered name) and re-matches
   the versions whose dictionary fingerprint is stale — skipping the expensive match
   when none of the names that changed occurs in that paper's text;
3. removes links of versions that are no longer current and entities nobody links to.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import (
    Document,
    DocumentElement,
    DocumentMetadata,
    DocumentReference,
    DocumentStatus,
    DocumentVersion,
    Section,
)
from app.models.knowledge import DocumentEntity, Entity, EntityExtraction
from app.services.knowledge.extract import (
    EXTRACTOR_VERSION,
    Dictionary,
    Discovered,
    PaperEntity,
    Passage,
    _squash,
    build_dictionary,
    discover,
    match,
)

log = get_logger(__name__)

_locks: dict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass
class EnsureStats:
    discovered: int = 0
    matched: int = 0
    skipped_match: int = 0
    removed_versions: int = 0
    removed_entities: int = 0
    ms: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class PaperText:
    title: str
    passages: list[Passage]
    references: list[str]

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.passages)


async def load_paper_text(session: AsyncSession, version_id: uuid.UUID, title: str) -> PaperText:
    sections = (
        await session.execute(
            select(Section).where(Section.version_id == version_id).order_by(Section.position)
        )
    ).scalars()
    passages: list[Passage] = []
    for section in sections:
        for index, paragraph in enumerate(section.paragraphs or []):
            text = (paragraph.get("text") or "").strip()
            if text:
                passages.append(
                    Passage(
                        text=text,
                        section_kind=section.kind,
                        page=int(paragraph.get("page_start") or section.page_start or 1),
                        section_id=str(section.id),
                        paragraph_index=index,
                    )
                )
    if not any(p.section_kind == "abstract" for p in passages):
        abstract = (
            await session.execute(
                select(DocumentMetadata.abstract).where(DocumentMetadata.version_id == version_id)
            )
        ).scalar_one_or_none()
        if abstract:
            passages.insert(0, Passage(abstract, "abstract", 1))
    captions = (
        await session.execute(
            select(DocumentElement.caption, DocumentElement.page).where(
                DocumentElement.version_id == version_id, DocumentElement.caption.is_not(None)
            )
        )
    ).all()
    passages.extend(Passage(caption, "caption", page) for caption, page in captions if caption)
    references = list(
        (
            await session.execute(
                select(DocumentReference.raw_text)
                .where(DocumentReference.version_id == version_id)
                .order_by(DocumentReference.position)
            )
        ).scalars()
    )
    return PaperText(title=title, passages=passages, references=references)


async def current_versions(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """[(document_id, current version_id, title)] of the user's readable papers."""
    rows = await session.execute(
        select(Document.id, Document.current_version_id, Document.title).where(
            Document.user_id == user_id,
            Document.status == DocumentStatus.READY,
            Document.current_version_id.is_not(None),
        )
    )
    return [
        (doc_id, version_id, title)
        for doc_id, version_id, title in rows.all()
        if version_id is not None
    ]


async def ensure_entities(session: AsyncSession, user_id: uuid.UUID) -> EnsureStats:
    async with _locks[user_id]:
        started = time.perf_counter()
        stats = EnsureStats()
        await _ensure(session, user_id, stats)
        stats.ms = round((time.perf_counter() - started) * 1000, 1)
        if stats.discovered or stats.matched or stats.removed_versions:
            log.info("entities_refreshed", user_id=str(user_id), **stats.__dict__)
        return stats


async def _ensure(session: AsyncSession, user_id: uuid.UUID, stats: EnsureStats) -> None:
    papers = await current_versions(session, user_id)
    current = {version_id: (doc_id, title) for doc_id, version_id, title in papers}
    extractions = {
        e.version_id: e
        for e in (
            await session.execute(
                select(EntityExtraction).where(EntityExtraction.user_id == user_id)
            )
        ).scalars()
    }

    # Versions that are no longer current (reprocessed, failed, deleted): drop their links.
    gone = [v for v in extractions if v not in current]
    if gone:
        await session.execute(delete(DocumentEntity).where(DocumentEntity.version_id.in_(gone)))
        await session.execute(delete(EntityExtraction).where(EntityExtraction.version_id.in_(gone)))
        for v in gone:
            extractions.pop(v)
        stats.removed_versions = len(gone)

    texts: dict[uuid.UUID, PaperText] = {}

    # 1. Discovery (per paper, independent of the rest of the library).
    for version_id, (doc_id, title) in current.items():
        record = extractions.get(version_id)
        if record and record.extractor_version == EXTRACTOR_VERSION and record.title == title:
            continue
        text = await load_paper_text(session, version_id, title)
        texts[version_id] = text
        found = await asyncio.to_thread(discover, title, text.passages, text.references)
        if record is None:
            record = EntityExtraction(version_id=version_id, user_id=user_id, document_id=doc_id)
            session.add(record)
            extractions[version_id] = record
        record.extractor_version = EXTRACTOR_VERSION
        record.title = title[:500]
        record.discovered = [d.as_dict() for d in found]
        record.dictionary_hash = None  # force a match
        stats.discovered += 1

    # 2. Matching against the library dictionary.
    dictionary = build_dictionary(
        Discovered.from_dict(item) for record in extractions.values() for item in record.discovered
    )
    fingerprint = dictionary.fingerprint
    surfaces = dictionary.surfaces()
    entity_ids: dict[tuple[str, str], uuid.UUID] = {
        (e.type, e.key): e.id
        for e in (await session.execute(select(Entity).where(Entity.user_id == user_id))).scalars()
    }
    for version_id, record in extractions.items():
        if record.dictionary_hash == fingerprint:
            continue
        doc_id, title = current[version_id]
        previous = set((record.stats or {}).get("surfaces", []))
        paper = texts.get(version_id)
        if record.dictionary_hash is not None and previous:
            # Only names that were added or removed can change this paper's links.
            changed = surfaces ^ previous
            if paper is None:
                full_text = (
                    await session.execute(
                        select(DocumentVersion.full_text).where(DocumentVersion.id == version_id)
                    )
                ).scalar_one_or_none() or ""
            else:
                full_text = paper.full_text
            haystack = _squash(full_text)
            if not any(_squash(s) in haystack for s in changed):
                record.dictionary_hash = fingerprint
                record.stats = {**(record.stats or {}), "surfaces": sorted(surfaces)}
                stats.skipped_match += 1
                continue
        if paper is None:
            paper = await load_paper_text(session, version_id, title)
        discovered = [Discovered.from_dict(item) for item in record.discovered]
        links = await asyncio.to_thread(match, title, paper.passages, dictionary, discovered)
        await _store_links(session, user_id, doc_id, version_id, links, entity_ids)
        record.dictionary_hash = fingerprint
        record.matched_at = datetime.now(UTC)
        record.stats = {
            "surfaces": sorted(surfaces),
            "links": len(links),
            "by_relation": {
                rel: sum(1 for link in links if link.relation == rel)
                for rel in ("proposes", "uses", "mentions")
            },
        }
        stats.matched += 1

    # 3. Entities nobody links to any more.
    await session.flush()
    linked = select(DocumentEntity.entity_id).where(DocumentEntity.user_id == user_id)
    result = await session.execute(
        delete(Entity).where(Entity.user_id == user_id, Entity.id.not_in(linked))
    )
    stats.removed_entities = int(getattr(result, "rowcount", 0) or 0)
    await session.commit()


async def _store_links(
    session: AsyncSession,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    found: list[PaperEntity],
    entity_ids: dict[tuple[str, str], uuid.UUID],
) -> None:
    await session.execute(delete(DocumentEntity).where(DocumentEntity.version_id == version_id))
    for item in found:
        ref = (item.type.value, item.key)
        entity_id = entity_ids.get(ref)
        if entity_id is None:
            entity = Entity(
                id=uuid.uuid4(),
                user_id=user_id,
                type=item.type.value,
                key=item.key[:200],
                name=item.name[:300],
                aliases=item.aliases[:30],
                info=item.info,
                source=item.source,
            )
            session.add(entity)
            await session.flush()  # the link below references it
            entity_ids[ref] = entity_id = entity.id
        else:
            existing = await session.get(Entity, entity_id)
            if existing is not None and set(item.aliases) - set(existing.aliases):
                existing.aliases = sorted(set(existing.aliases) | set(item.aliases))[:30]
        session.add(
            DocumentEntity(
                user_id=user_id,
                entity_id=entity_id,
                document_id=document_id,
                version_id=version_id,
                relation=item.relation,
                mentions=item.mentions,
                score=item.score,
                variants=item.variants,
                evidence=[e.as_dict() for e in item.evidence],
            )
        )


__all__ = ["Dictionary", "EnsureStats", "current_versions", "ensure_entities", "load_paper_text"]

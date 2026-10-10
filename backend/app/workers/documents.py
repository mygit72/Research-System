"""`document.process` job: parse → structure → metadata → persist → thumbnail → dedupe.

Parsing is CPU-bound and synchronous (PyMuPDF), so it runs in a worker thread;
progress callbacks from that thread are marshalled back onto the event loop.
Later phases append chunking / embedding / indexing stages here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.document import (
    Document,
    DocumentElement,
    DocumentMetadata,
    DocumentReference,
    DocumentStatus,
    DocumentVersion,
    DuplicateKind,
    Page,
    Section,
)
from app.repositories.documents import DocumentRepository
from app.services.documents import INDEX_JOB, PROCESS_JOB, authors_display, find_duplicate
from app.services.embeddings import EmbeddingError
from app.services.indexing import index_version, mark_index_failed
from app.services.ingestion.cleaning import normalize_title
from app.services.ingestion.ocr import build_ocr_provider
from app.services.ingestion.parsers import ParseError, default_registry
from app.services.ingestion.pipeline import PIPELINE_VERSION, PipelineResult, run_pipeline
from app.services.ingestion.render import render_page_png
from app.services.ingestion.types import DocumentFormat, ExtractedMetadata
from app.services.jobs import JobService
from app.services.knowledge.entities import ensure_entities
from app.services.storage import get_storage
from app.services.summaries import auto_summarize
from app.workers.dispatcher import get_dispatcher
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted

log = get_logger(__name__)

# Overall progress allotted to each stage (parsing dominates).
STAGES = {
    "parsing": (0.02, 0.50),
    "ocr": (0.02, 0.50),
    "structure": (0.50, 0.55),
    "metadata": (0.55, 0.58),
    "saving": (0.58, 0.62),
    "chunking": (0.62, 0.66),
    "embedding": (0.66, 0.90),
    "indexing": (0.90, 0.94),
    "thumbnail": (0.94, 0.97),
    "duplicates": (0.97, 0.98),
    "entities": (0.98, 0.995),
}
_METADATA_FIELDS = (
    "title", "authors", "affiliations", "abstract", "year", "publication_date", "venue",
    "doi", "arxiv_id", "keywords", "research_area",
)  # fmt: skip


class _ProgressRelay:
    """Thread-safe bridge from the parser thread to async job progress updates."""

    def __init__(self, ctx: JobContext, loop: asyncio.AbstractEventLoop) -> None:
        self.ctx = ctx
        self.loop = loop
        self._last_sent = 0.0
        self._last_stage = ""
        self._pending: list[Any] = []

    def overall(self, stage: str, fraction: float) -> float:
        start, end = STAGES.get(stage, (0.0, 1.0))
        return start + (end - start) * max(0.0, min(fraction, 1.0))

    def __call__(self, stage: str, fraction: float, message: str | None) -> None:
        now = time.monotonic()
        if stage == self._last_stage and now - self._last_sent < 0.4:  # throttle DB writes
            return
        self._last_stage, self._last_sent = stage, now
        future = asyncio.run_coroutine_threadsafe(
            self.ctx.report(stage, self.overall(stage, fraction), message), self.loop
        )
        self._pending.append(future)

    async def flush(self) -> None:
        """Wait for progress writes from the worker thread (so none land after completion)."""
        pending, self._pending = self._pending, []
        await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)

    async def stage(self, stage: str, message: str) -> None:
        await self.flush()
        self._last_stage = stage
        await self.ctx.report(stage, self.overall(stage, 0.0), message)


@on_interrupted(PROCESS_JOB, INDEX_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _mark_failed(ctx, uuid.UUID(ctx.payload["version_id"]), message)


@job_handler(PROCESS_JOB)
async def process_document(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    storage = get_storage(settings)
    version_id = uuid.UUID(ctx.payload["version_id"])

    async with ctx.session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        if version is None:
            raise JobFailedError(
                "This file no longer exists.", detail=f"version {version_id} missing"
            )
        document = await session.get(Document, version.document_id)
        assert document is not None
        document_id = document.id
        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        file_path = storage.path(version.storage_key)
        fmt = DocumentFormat(document.doc_type)
        filename = version.original_filename
        await session.commit()

    relay = _ProgressRelay(ctx, asyncio.get_running_loop())
    await relay.stage("parsing", "Reading the document")
    registry = default_registry(build_ocr_provider(settings.ocr_enabled))
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(run_pipeline, file_path, fmt, filename, registry, relay)
    except ParseError as exc:
        await relay.flush()
        await _mark_failed(ctx, version_id, exc.user_message)
        raise JobFailedError(exc.user_message, detail=exc.detail) from exc
    except Exception as exc:
        await relay.flush()
        message = "We couldn't process this document. The file may be corrupted or unusual."
        await _mark_failed(ctx, version_id, message)
        raise JobFailedError(message, detail=repr(exc)) from exc
    metrics.observe(
        "document_parse_duration_ms", (time.perf_counter() - started) * 1000, format=fmt.value
    )

    await relay.stage("saving", "Saving sections, figures and tables")
    await _persist(ctx, version_id, result)

    index_info = await _index(ctx, relay, version_id, settings)

    has_thumbnail = False
    if fmt == DocumentFormat.PDF:
        await relay.stage("thumbnail", "Rendering preview")
        has_thumbnail = await asyncio.to_thread(
            _render_thumbnail, file_path, storage.derived_dir(version_id)
        )

    await relay.stage("duplicates", "Checking for duplicates")
    duplicate = await _finish(ctx, version_id, has_thumbnail)
    await relay.stage("entities", "Finding datasets, models and methods")
    entities = await _extract_entities(ctx)
    await relay.flush()
    summary = "skipped"
    if index_info["status"] == "indexed":
        summary = await auto_summarize(
            ctx.session_factory,
            settings,
            lambda session: JobService(session, get_dispatcher(settings)),
            document_id,
        )
    stats = result.stats
    metrics.inc("documents_processed_total", format=fmt.value)
    log.info(
        "document_processed",
        version_id=str(version_id),
        **{k: v for k, v in stats.items() if k != "timings_ms"},
    )
    return {
        "version_id": str(version_id),
        "stats": stats,
        "index": index_info,
        "duplicate": duplicate,
        "summary": summary,
        "entities": entities,
    }


async def _extract_entities(ctx: JobContext) -> dict[str, Any]:
    """Link the paper (and re-link the library) to datasets / models / methods.

    Deterministic and fast; a failure here never fails the upload — the knowledge views
    retry it on their next read.
    """
    try:
        async with ctx.session_factory() as session:
            stats = await ensure_entities(session, ctx.user_id)
    except Exception as exc:
        log.error("entity_extraction_failed", user_id=str(ctx.user_id), error=repr(exc))
        return {"status": "failed"}
    return {
        "status": "ok",
        "discovered": stats.discovered,
        "matched": stats.matched,
        "ms": stats.ms,
    }


async def _index(
    ctx: JobContext, relay: _ProgressRelay, version_id: uuid.UUID, settings: Any
) -> dict[str, Any]:
    """Chunk + embed + index. Failure leaves the paper readable but flagged as not searchable."""
    await relay.stage("chunking", "Splitting the paper into passages")
    try:
        result = await index_version(ctx.session_factory, version_id, settings, relay)
    except EmbeddingError as exc:
        await relay.flush()
        return await _index_failed(ctx, version_id, exc.user_message, exc.detail)
    except Exception as exc:  # vector store down, etc. -- never silent
        await relay.flush()
        return await _index_failed(
            ctx, version_id, "Search indexing failed. The paper can still be read.", repr(exc)
        )
    await relay.flush()
    return {
        "status": "indexed",
        "chunks": result.chunks,
        "embedded": result.embedded,
        "cached": result.cached,
        "model": result.model_id,
        "strategy": result.strategy,
        "timings_ms": result.timings_ms,
    }


async def _index_failed(
    ctx: JobContext, version_id: uuid.UUID, message: str, detail: str | None
) -> dict[str, Any]:
    log.error("indexing_failed", version_id=str(version_id), error=message, detail=detail)
    async with ctx.session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        document_id = version.document_id if version else None
    if document_id:
        await mark_index_failed(ctx.session_factory, document_id, message)
    return {"status": "failed", "error": message}


@job_handler(INDEX_JOB)
async def index_document(ctx: JobContext) -> dict[str, Any]:
    """Re-run search indexing only (retry after a failure, merged versions, new strategy)."""
    settings = get_settings()
    version_id = uuid.UUID(ctx.payload["version_id"])
    relay = _ProgressRelay(ctx, asyncio.get_running_loop())
    info = await _index(ctx, relay, version_id, settings)
    if info["status"] == "failed":
        raise JobFailedError(info["error"])
    return info


def _render_thumbnail(pdf_path: Path, target_dir: Path) -> bool:
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "thumb.png").write_bytes(render_page_png(pdf_path, 1, 320))
        return True
    except Exception as exc:  # a missing preview must not fail the document
        log.warning("thumbnail_failed", error=repr(exc))
        return False


async def _mark_failed(ctx: JobContext, version_id: uuid.UUID, message: str) -> None:
    async with ctx.session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        if version is not None and (document := await session.get(Document, version.document_id)):
            document.status = DocumentStatus.FAILED
            document.error_message = message
            await session.commit()


def _apply_metadata(record: DocumentMetadata, extracted: ExtractedMetadata) -> None:
    protected = set(record.user_corrected_fields or [])
    provenance = dict(record.provenance or {})
    for field in _METADATA_FIELDS:
        if field in protected:
            continue
        setattr(record, field, getattr(extracted, field))
        if field in extracted.provenance:
            provenance[field] = extracted.provenance[field]
        else:
            provenance.pop(field, None)
    record.provenance = provenance
    record.normalized_title = normalize_title(record.title) if record.title else None


async def _persist(ctx: JobContext, version_id: uuid.UUID, result: PipelineResult) -> None:
    async with ctx.session_factory() as session:
        repo = DocumentRepository(session)
        version = await session.get(DocumentVersion, version_id)
        assert version is not None
        document = await session.get(Document, version.document_id)
        assert document is not None
        await repo.clear_extraction(version_id)

        structure, raw = result.structure, result.raw
        for info in raw.pages:
            start, end = structure.page_spans.get(info.number, (0, 0))
            session.add(
                Page(
                    version_id=version_id,
                    number=info.number,
                    width=info.width,
                    height=info.height,
                    char_start=start,
                    char_end=end,
                    used_ocr=info.used_ocr,
                )
            )

        position = 0

        def add_sections(nodes: list[Any], parent_id: uuid.UUID | None) -> None:
            nonlocal position
            for node in nodes:
                section_id = uuid.uuid4()
                session.add(
                    Section(
                        id=section_id,
                        version_id=version_id,
                        parent_id=parent_id,
                        position=position,
                        level=node.level,
                        kind=node.kind.value,
                        title=node.title[:500],
                        number=node.number,
                        page_start=node.page_start,
                        page_end=node.page_end,
                        char_start=node.char_start,
                        char_end=node.char_end,
                        paragraphs=[p.to_dict() for p in node.paragraphs],
                    )
                )
                position += 1
                add_sections(node.children, section_id)

        add_sections(structure.sections, None)
        await session.flush()  # parents before children for FK checks

        for index, element in enumerate(structure.elements):
            session.add(
                DocumentElement(
                    version_id=version_id,
                    kind=element.kind,
                    position=index,
                    label=element.label,
                    number=element.number,
                    caption=element.caption,
                    page=element.page,
                    bbox=list(element.bbox) if element.bbox else None,
                    content=element.content,
                    context=element.context,
                )
            )
        for reference in structure.references:
            session.add(
                DocumentReference(
                    version_id=version_id,
                    position=reference.index,
                    raw_text=reference.raw_text,
                    title=reference.title,
                    year=reference.year,
                    doi=reference.doi,
                    arxiv_id=reference.arxiv_id,
                )
            )

        record = await repo.get_metadata(version_id)
        if record is None:
            record = DocumentMetadata(version_id=version_id, user_id=version.user_id)
            session.add(record)
        _apply_metadata(record, result.metadata)

        version.full_text = structure.full_text
        version.page_count = len(raw.pages) if raw.paginated else None
        version.paginated = raw.paginated
        version.used_ocr = bool(raw.ocr_pages)
        version.ocr_pages = raw.ocr_pages
        version.parser = raw.parser[:64]
        version.processed_at = datetime.now(UTC)
        version.processing_config = {
            "pipeline_version": PIPELINE_VERSION,
            "parser": raw.parser,
            "ocr_enabled": get_settings().ocr_enabled,
            "stats": result.stats,
        }

        if not document.title_is_user_set and record.title:
            document.title = record.title[:500]
        document.year = record.year
        document.authors_display = authors_display(record.authors or [])[:500]
        document.page_count = version.page_count
        document.warnings = raw.warnings
        await session.commit()


async def _finish(ctx: JobContext, version_id: uuid.UUID, has_thumbnail: bool) -> str | None:
    async with ctx.session_factory() as session:
        repo = DocumentRepository(session)
        version = await session.get(DocumentVersion, version_id)
        assert version is not None
        document = await session.get(Document, version.document_id)
        assert document is not None
        version.has_thumbnail = has_thumbnail

        if document.duplicate_kind != DuplicateKind.EXACT.value:
            match = find_duplicate(
                file_match=None,
                metadata=await repo.get_metadata(version_id),
                candidates=await repo.metadata_candidates(document.user_id, document.id),
            )
            document.duplicate_kind, document.duplicate_of_id = None, None
            if match is not None:
                other = await session.get(Document, match.document_id)
                if other is not None and _as_utc(other.created_at) > _as_utc(document.created_at):
                    # The other upload is newer (it just finished first): flag it, not us.
                    if other.duplicate_kind is None:
                        other.duplicate_kind = match.kind.value
                        other.duplicate_of_id = document.id
                else:
                    document.duplicate_kind = match.kind.value
                    document.duplicate_of_id = match.document_id

        document.status = DocumentStatus.READY
        document.error_message = None
        await session.commit()
        return document.duplicate_kind


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)

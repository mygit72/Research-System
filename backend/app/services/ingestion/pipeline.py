"""Pure (DB-free) ingestion pipeline: file → parsed, structured, described document.

Kept free of I/O besides reading the file so it can run in a worker thread,
in Celery, or directly in tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.ingestion.metadata import extract_metadata
from app.services.ingestion.parsers import ParserRegistry, ProgressCallback
from app.services.ingestion.parsers.base import noop_progress
from app.services.ingestion.structure import build_structure
from app.services.ingestion.types import (
    DocumentFormat,
    DocumentStructure,
    ExtractedMetadata,
    RawDocument,
)

PIPELINE_VERSION = "2.0"  # bump when parsing output changes (recorded per version)


@dataclass
class PipelineResult:
    raw: RawDocument
    structure: DocumentStructure
    metadata: ExtractedMetadata
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def stats(self) -> dict[str, object]:
        sections = self.structure.all_sections()
        return {
            "pages": len(self.raw.pages),
            "blocks": len(self.raw.blocks),
            "sections": len(sections),
            "paragraphs": sum(len(s.paragraphs) for s in sections),
            "figures": sum(1 for e in self.structure.elements if e.kind == "figure"),
            "tables": sum(1 for e in self.structure.elements if e.kind == "table"),
            "equations": sum(1 for e in self.structure.elements if e.kind == "equation"),
            "references": len(self.structure.references),
            "characters": len(self.structure.full_text),
            "ocr_pages": self.raw.ocr_pages,
            "timings_ms": self.timings_ms,
        }


def run_pipeline(
    path: Path,
    fmt: DocumentFormat,
    filename: str,
    registry: ParserRegistry,
    progress: ProgressCallback | None = None,
) -> PipelineResult:
    progress = progress or noop_progress
    timings: dict[str, float] = {}

    started = time.perf_counter()
    raw = registry.for_format(fmt).parse(path, progress)
    timings["parse"] = round((time.perf_counter() - started) * 1000, 1)

    progress("structure", 0.0, "Detecting sections, figures and tables")
    started = time.perf_counter()
    structure = build_structure(raw)
    timings["structure"] = round((time.perf_counter() - started) * 1000, 1)

    progress("metadata", 0.0, "Extracting title, authors and identifiers")
    started = time.perf_counter()
    metadata = extract_metadata(raw, structure, filename)
    timings["metadata"] = round((time.perf_counter() - started) * 1000, 1)
    return PipelineResult(raw=raw, structure=structure, metadata=metadata, timings_ms=timings)

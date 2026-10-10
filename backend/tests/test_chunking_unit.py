from __future__ import annotations

import itertools
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.demo import sample_papers as sp
from app.services.chunking import (
    Chunker,
    ChunkingConfig,
    ChunkingStrategy,
    ChunkSource,
    source_from_sections,
)
from app.services.chunking.chunkers import SourceParagraph, SourceSection
from app.services.chunking.sentences import sentence_spans
from app.services.chunking.tokens import ApproximateTokenCounter
from app.services.embeddings import HashingEmbeddingProvider
from app.services.ingestion.ocr import DisabledOCRProvider
from app.services.ingestion.parsers import default_registry
from app.services.ingestion.pipeline import run_pipeline
from app.services.ingestion.types import DocumentFormat

COUNTER = ApproximateTokenCounter()
EMBED = HashingEmbeddingProvider().embed_documents


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> ChunkSource:
    path = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path_factory.mktemp("c") / "p.pdf")
    result = run_pipeline(
        path, DocumentFormat.PDF, "p.pdf", default_registry(DisabledOCRProvider())
    )
    rows: list[SimpleNamespace] = []

    def walk(nodes, parent):  # type: ignore[no-untyped-def]
        for node in nodes:
            section_id = uuid.uuid4()
            rows.append(
                SimpleNamespace(
                    id=section_id,
                    parent_id=parent,
                    title=node.title,
                    number=node.number,
                    kind=node.kind.value,
                    paragraphs=[p.to_dict() for p in node.paragraphs],
                )
            )
            walk(node.children, section_id)

    walk(result.structure.sections, None)
    return source_from_sections(
        result.metadata.title or "", result.structure.full_text, result.structure.page_spans, rows
    )


def test_sentence_spans_respect_scientific_abbreviations() -> None:
    text = (
        "As shown by Smith et al. in Fig. 3, recall rises to 7.3 points. "
        "J. Doe disagrees (see Eq. 2). Results improve! Next, we test."
    )
    sentences = [text[s:e] for s, e in sentence_spans(text)]
    assert sentences == [
        "As shown by Smith et al. in Fig. 3, recall rises to 7.3 points.",
        "J. Doe disagrees (see Eq. 2).",
        "Results improve!",
        "Next, we test.",
    ]
    assert sentence_spans("abc", offset=10) == [(10, 13)]


@pytest.mark.parametrize("strategy", list(ChunkingStrategy))
def test_every_strategy_produces_exact_citable_spans(
    source: ChunkSource, strategy: ChunkingStrategy
) -> None:
    chunks = Chunker(
        ChunkingConfig(strategy=strategy, chunk_size=96, chunk_overlap=16), COUNTER, embed=EMBED
    ).chunk(source)
    assert chunks
    for chunk in chunks:
        if chunk.kind != "table":
            assert source.full_text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.page_start <= chunk.page_end
        assert chunk.text.strip()
    covered = "".join(c.text for c in chunks)
    assert "reciprocal rank fusion" in covered.lower()


def test_section_aware_never_crosses_sections(source: ChunkSource) -> None:
    chunks = Chunker(ChunkingConfig(chunk_size=64, chunk_overlap=8), COUNTER).chunk(source)
    ranges = {s.key: (s.char_start, s.char_end) for s in source.sections if s.paragraphs}
    for chunk in chunks:
        start, end = ranges[chunk.section_key]  # type: ignore[index]
        assert start <= chunk.char_start and chunk.char_end <= end
    kinds = {c.kind for c in chunks}
    assert {"table", "equation", "caption"} <= kinds  # atomic elements stay whole
    table = next(c for c in chunks if c.kind == "table")
    assert table.text.startswith("| Method | Recall@10")
    subsection = next(c for c in chunks if c.section_title == "Training Objective")
    assert subsection.context_header.endswith("3 Method › 3.1 Training Objective")
    assert subsection.embedding_text.startswith(sp.RETRIEVAL_PAPER.title)


def test_size_limits_and_overlap(source: ChunkSource) -> None:
    config = ChunkingConfig(strategy=ChunkingStrategy.FIXED, chunk_size=50, chunk_overlap=10)
    chunks = Chunker(config, COUNTER).chunk(source)
    assert all(c.token_count <= 52 for c in chunks)  # re-tokenized slices may differ slightly
    assert any(a.char_end > b.char_start for a, b in itertools.pairwise(chunks))

    aware = Chunker(ChunkingConfig(chunk_size=80, chunk_overlap=0), COUNTER).chunk(source)
    assert all(c.token_count <= 80 or c.kind in {"table", "equation"} for c in aware)


def test_oversized_table_is_split_with_repeated_header() -> None:
    rows = "\n".join(f"| model-{i} | {i}.0 |" for i in range(40))
    table = f"| Model | Score |\n| --- | --- |\n{rows}"
    section = SourceSection(
        key="s1",
        title="Results",
        path=["5 Results"],
        kind="results",
        paragraphs=[SourceParagraph(table, "table", 1, 1, 0, len(table))],
    )
    src = ChunkSource("Paper", table, [section], {1: (0, len(table))})
    parts = Chunker(ChunkingConfig(chunk_size=60, chunk_overlap=0), COUNTER).chunk(src)
    assert len(parts) > 1
    assert all(p.text.startswith("| Model | Score |\n| --- | --- |") for p in parts)
    assert all(p.token_count <= 60 for p in parts)


def test_semantic_chunking_splits_at_topic_shift() -> None:
    topic_a = " ".join(
        f"Retrieval uses BM25 ranking and dense vectors for passage search variant {i}."
        for i in range(4)
    )
    topic_b = " ".join(
        f"Protein folding simulations model amino acid chains in water case {i}." for i in range(4)
    )
    text = f"{topic_a} {topic_b}"
    section = SourceSection(
        key="s", title="Mixed", path=["Mixed"], kind="other",
        paragraphs=[SourceParagraph(text, "text", 1, 1, 0, len(text))],
    )  # fmt: skip
    src = ChunkSource("Paper", text, [section], {1: (0, len(text))})
    config = ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC, chunk_size=500, chunk_overlap=0)
    chunks = Chunker(config, COUNTER, embed=EMBED).chunk(src)
    boundary = len(topic_a) + 1
    assert any(c.char_start == boundary for c in chunks), [
        (c.char_start, c.text[:30]) for c in chunks
    ]
    assert all("Protein" not in c.text or "BM25" not in c.text for c in chunks)


def test_invalid_config() -> None:
    with pytest.raises(ValueError, match="overlap"):
        Chunker(ChunkingConfig(chunk_size=50, chunk_overlap=50), COUNTER)
    with pytest.raises(ValueError, match="semantic"):
        Chunker(ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC), COUNTER)


def test_approximate_counter_is_conservative() -> None:
    text = "Parameter-efficient fine-tuning with low-rank adapters (LoRA) reduces memory."
    assert COUNTER.count(text) >= len(text.split())
    assert len(COUNTER.spans(text)) == COUNTER.count(text)
    assert np.all(np.diff([s for s, _ in COUNTER.spans(text)]) > 0)


def test_source_paths(tmp_path: Path) -> None:
    parent = SimpleNamespace(
        id=uuid.uuid4(), parent_id=None, title="Method", number="3", kind="method", paragraphs=[]
    )
    child = SimpleNamespace(
        id=uuid.uuid4(), parent_id=parent.id, title="Loss", number="3.1", kind="method",
        paragraphs=[{"text": "x", "kind": "text", "page_start": 1, "page_end": 1, "char_start": 0, "char_end": 1, "boxes": []}],
    )  # fmt: skip
    src = source_from_sections("T", "x", {1: (0, 1)}, [parent, child])
    assert src.sections[1].path == ["3 Method", "3.1 Loss"]

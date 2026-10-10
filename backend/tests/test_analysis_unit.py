"""Disagreements, gaps, deep-research planning and budgets, exports (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.report import ResearchReport
from app.services.analysis import export
from app.services.analysis.deep_research import Budget, BudgetExceeded, parse_subquestions
from app.services.analysis.digests import Digest, SourceBook, Statement
from app.services.analysis.disagreements import describe, find_disagreements
from app.services.analysis.gaps import (
    SYNTHESIS,
    Gap,
    combination_gaps,
    parse_directions,
)
from app.services.analysis.writing import Writer
from app.services.knowledge.library import EntityInfo, Library, Link
from app.services.rag.verify import LexicalVerifier


def source(doc: uuid.UUID, title: str, quote: str, chunk: str) -> dict[str, object]:
    return {
        "chunk_id": chunk,
        "document": {"id": str(doc), "title": title, "year": 2024},
        "quote": quote,
        "page_start": 3,
        "section_title": "Results",
    }


def digest(title: str, statements: list[tuple[str, str]]) -> Digest:
    doc = uuid.uuid4()
    d = Digest(doc, title, 2024, "", uuid.uuid4())
    for i, (field, text) in enumerate(statements):
        d.statements.append(
            Statement(field, text, "supported", [source(doc, title, text, f"{title}-{i}")])
        )
    return d


def library_for(digests: list[Digest], uses: dict[str, list[tuple[str, str]]]) -> Library:
    """uses: paper title → [(entity type, entity name)]."""
    entities: dict[uuid.UUID, EntityInfo] = {}
    by_name: dict[str, uuid.UUID] = {}
    links = []
    for d in digests:
        for kind, name in uses.get(d.title, []):
            if name not in by_name:
                by_name[name] = uuid.uuid4()
                entities[by_name[name]] = EntityInfo(by_name[name], kind, name, [], {}, "catalog")
            links.append(Link(d.document_id, by_name[name], "uses", 3, 3.0, [], []))
    return Library(uuid.uuid4(), {}, {}, {}, [], entities, links, {}, None, "")


def test_disagreements_need_shared_setup_and_report_context() -> None:
    a = digest("Paper A", [("results", "LoRA improves accuracy on GLUE by two points.")])
    b = digest("Paper B", [("results", "LoRA does not improve accuracy on GLUE in our runs.")])
    c = digest("Paper C", [("results", "LoRA does not improve accuracy on SQuAD.")])
    library = library_for(
        [a, b, c],
        {
            "Paper A": [("method", "LoRA"), ("dataset", "GLUE"), ("model", "RoBERTa")],
            "Paper B": [("method", "LoRA"), ("dataset", "GLUE"), ("model", "GPT-2")],
            "Paper C": [("dataset", "SQuAD")],
        },
    )
    found = find_disagreements([a, b, c], library, LexicalVerifier())
    # A vs C share nothing; B vs C share nothing: only A vs B is a candidate.
    assert len(found) == 1 and found[0].method == "polarity"
    assert sorted(found[0].shared) == ["GLUE", "LoRA"]
    item = describe(found[0], library, SourceBook())
    assert item["label"] == "Potential disagreement"
    assert item["differences"]["model"] == {"a": ["RoBERTa"], "b": ["GPT-2"]}
    assert item["claim_a"]["citations"] == [1] and item["claim_b"]["citations"] == [2]


def test_agreeing_statements_are_not_flagged() -> None:
    a = digest("A", [("results", "LoRA improves accuracy on GLUE.")])
    b = digest("B", [("results", "LoRA also improves accuracy on GLUE.")])
    library = library_for([a, b], {"A": [("dataset", "GLUE")], "B": [("dataset", "GLUE")]})
    assert find_disagreements([a, b], library, LexicalVerifier()) == []


def test_untested_combinations_skip_generic_methods() -> None:
    papers = [digest(f"P{i}", []) for i in range(4)]
    library = library_for(
        papers,
        {
            "P0": [("method", "LoRA"), ("dataset", "MMLU"), ("method", "Adam")],
            "P1": [("dataset", "SQuAD"), ("method", "Adam")],
            "P2": [("dataset", "SQuAD"), ("method", "Adam")],
            "P3": [("dataset", "MMLU"), ("method", "Adam"), ("method", "LoRA")],
        },
    )
    gaps = combination_gaps(papers, library, start=1)
    titles = [g.title for g in gaps]
    assert "Untested here: LoRA on SQuAD" in titles
    assert not any("Adam" in t for t in titles)  # used by every paper: a building block
    assert not any("MMLU" in t and "LoRA" in t for t in titles)  # P3 tests LoRA on MMLU
    assert all(g.origin == SYNTHESIS and g.papers for g in gaps)


def test_directions_must_cite_a_gap() -> None:
    gaps = [
        Gap("G1", "stated", "Stated by the authors", "Only English", "Evaluated only on English.",
            papers=[{"id": "p1", "title": "A", "year": 2023}]),
        Gap("G2", "combination", SYNTHESIS, "Untested: LoRA on SQuAD", "…",
            papers=[{"id": "p2", "title": "B", "year": 2024}]),
    ]  # fmt: skip
    reply = (
        "Evaluate the adapters on multilingual benchmarks [1].\n"
        "Try LoRA for extractive question answering on SQuAD [2].\n"
        "Scale everything up a lot.\n"
        "Combine both ideas in one study [1][2]."
    )
    directions = parse_directions(reply, gaps)
    assert [d["based_on"] for d in directions] == [["G1"], ["G2"], ["G1", "G2"]]
    assert directions[2]["papers"] == [
        {"id": "p1", "title": "A", "year": 2023},
        {"id": "p2", "title": "B", "year": 2024},
    ]
    assert (
        parse_directions("I couldn't find sufficient evidence in the indexed papers.", gaps) == []
    )


def test_planning_and_budget() -> None:
    reply = "1. What is reciprocal rank fusion?\n2) How is BM25 combined with dense retrieval?\nOk"
    assert parse_subquestions(reply, "q") == [
        "What is reciprocal rank fusion?",
        "How is BM25 combined with dense retrieval?",
    ]
    assert parse_subquestions("", "The original question") == ["The original question"]

    writer = Writer(llm=None, params=None, verifier=None, book=SourceBook())  # type: ignore[arg-type]
    budget = Budget(max_steps=2, max_tokens=1000, timeout=60)
    budget.spend(writer)
    budget.spend(writer)
    with pytest.raises(BudgetExceeded, match="step limit"):
        budget.spend(writer)
    tokens = Budget(max_steps=10, max_tokens=100, timeout=60)
    writer.tokens["input"] = 150
    with pytest.raises(BudgetExceeded, match="token budget"):
        tokens.spend(writer)
    late = Budget(max_steps=10, max_tokens=10**6, timeout=0)
    with pytest.raises(BudgetExceeded, match="time limit"):
        late.spend(writer)


def _report() -> ResearchReport:
    report = ResearchReport(
        user_id=uuid.uuid4(),
        kind="review",
        title="Adapters | a review",
        query="adapters",
        document_ids=["a", "b"],
        sections=[
            {"key": "overview", "title": "Overview", "kind": "text", "origin": "generated",
             "label": "Well supported", "text": "Adapters are cheap [1].\n\n- one\n- two"},
            {"key": "comparison", "title": "Comparison", "kind": "table", "data": {"rows": [
                {"document": {"title": "A | B", "year": 2023}, "approach": "PEFT",
                 "datasets": ["GLUE"], "metrics": ["F1"], "result": "Good.", "citations": [1]}]}},
            {"key": "gaps", "title": "Gaps", "kind": "gaps", "data": {"gaps": [
                {"id": "G1", "origin": "Stated by the authors", "title": "English only",
                 "text": "Only English.", "papers": [{"title": "A"}],
                 "statements": [{"citations": [1]}]}],
                "directions": [{"text": "Go multilingual.", "based_on": ["G1"]}]}},
        ],
        sources=[{"number": 1, "document": {"title": "A", "year": 2023}, "quote": "Cheap.",
                  "page_start": 2, "section_title": "Method"}],
        support={"explanation": "1 of 1 written statements are directly supported."},
        generation_config={"llm_model": "qwen2.5:3b"},
    )  # fmt: skip
    report.created_at = datetime(2026, 10, 2, tzinfo=UTC)
    return report


def test_exports_carry_text_labels_and_sources() -> None:
    report = _report()
    md = export.to_markdown(report)
    assert md.startswith("# Adapters | a review")
    assert "*Literature review · 02 Oct 2026 · 2 papers · written by qwen2.5:3b*" in md
    assert "Adapters are cheap [1]." in md and "- one\n- two" in md
    assert "| A \\| B | 2023 | PEFT | GLUE | F1 | Good. [1] |" in md
    assert "### Stated by the authors" in md and "(from G1)" in md
    assert "[1] A (2023), Method, p. 2: “Cheap.…”" in md
    assert export.to_docx(report)[:2] == b"PK"
    assert export.to_pdf(report)[:4] == b"%PDF"
    assert "<table>" in export.to_html(report) and "&lt;" not in export.to_html(report)
    assert export.filename(report, "md") == "adapters-a-review.md"


# --- writing: what the real model got wrong -------------------------------------------------------


def test_citation_formats_seen_from_the_model_are_normalized() -> None:
    from app.services.analysis.writing import normalize_citations

    assert normalize_citations("Costly to deploy (5). Methods help (5, 6).", 8) == (
        "Costly to deploy [5]. Methods help [5][6]."
    )
    assert normalize_citations("LoRA (2021) is cheap (12).", 8) == "LoRA (2021) is cheap (12)."
    assert normalize_citations("<direction> [2] Try it.", 3) == "[2] Try it."


async def test_reports_keep_only_what_the_passages_support() -> None:
    from app.services.analysis.writing import Writer

    book = SourceBook()
    lora = uuid.uuid4()
    one = book.add(
        source(
            lora, "LoRA", "LoRA freezes the pretrained weights and trains low-rank matrices.", "c1"
        )
    )
    two = book.add(
        source(lora, "LoRA", "We evaluate on GLUE and report accuracy for every task.", "c2")
    )
    writer = Writer(llm=None, params=None, verifier=LexicalVerifier(), book=book)  # type: ignore[arg-type]
    text = (
        "LoRA freezes the pretrained weights and trains low-rank matrices [2]. "  # wrong passage
        "It runs on edge devices and low-power IoT hardware [1]. "  # supported by nothing
        "The authors evaluate on GLUE and report accuracy for every task."  # uncited
    )
    section = await writer.check("overview", "Overview", text, [one, two])
    assert section["text"] == (
        "LoRA freezes the pretrained weights and trains low-rank matrices [1]. "
        "The authors evaluate on GLUE and report accuracy for every task [2]."
    )
    notes = [c.get("note") for c in section["claims"]]
    assert notes == ["Citation corrected by the checker", "Citation added by the checker"]
    assert [r["text"] for r in section["removed"]] == [
        "It runs on edge devices and low-power IoT hardware."
    ]
    assert section["status"] == "supported"
    assert "1 sentence the model wrote was removed" in support_summary_of([section])


def support_summary_of(sections: list[dict[str, object]]) -> str:
    from app.services.analysis.writing import support_summary

    return str(support_summary(sections, "lexical")["explanation"])


def test_directions_written_with_placeholders_and_leading_markers() -> None:
    gaps = [
        Gap("G1", "stated", "Stated by the authors", "Only English", "…",
            papers=[{"id": "p1", "title": "A", "year": 2023}]),
        Gap("G2", "combination", SYNTHESIS, "Untested: LoRA on SQuAD", "…",
            papers=[{"id": "p2", "title": "B", "year": 2024}]),
    ]  # fmt: skip
    reply = (
        "<direction> [1] Investigate the optimal rank for multilingual data.\n\n"
        "<direction> [2] Evaluate LoRA on the SQuAD dataset to see if it helps."
    )
    assert [d["based_on"] for d in parse_directions(reply, gaps)] == [["G1"], ["G2"]]


def test_one_mention_is_not_a_combination_gap() -> None:
    papers = [digest(f"P{i}", []) for i in range(3)]
    library = library_for(
        papers,
        {
            "P0": [("model", "GPT-4"), ("dataset", "QQP")],
            "P1": [("dataset", "QQP")],
            "P2": [("dataset", "SST-2")],
        },
    )
    assert combination_gaps(papers, library, start=1) == []  # GPT-4 is used by one paper only


def test_questions_without_citations_get_related_passages() -> None:
    from app.services.projects.generate import related_passages

    book = SourceBook()
    doc = uuid.uuid4()
    a = book.add(
        source(
            doc, "QLoRA", "QLoRA quantizes the model to 4-bit and trains low-rank adapters.", "a"
        )
    )
    b = book.add(source(doc, "BERT", "BERT is pre-trained with masked language modeling.", "b"))
    question = "Does training low-rank adapters on a 4-bit quantized model lose accuracy?"
    assert related_passages(question, [a, b], book) == [a]

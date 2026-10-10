"""Paper summaries: field parsing, passage selection, verification, job + API end to end."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.models.document import Chunk
from app.services.llm import FakeLLM, LLMError
from app.services.rag.citations import validate_citations
from app.services.rag.verify import LexicalVerifier
from app.services.summaries import FIELDS, NOT_REPORTED, PROMPT_VERSION, staleness
from app.services.summaries.engine import build_section
from app.services.summaries.passages import PaperPassages
from app.services.summaries.prompt import has_label, parse_fields
from app.services.summaries.spec import GROUPS, PROBLEM, RESULTS, TAKEAWAY
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_indexing_api import upload

OVERVIEW, METHOD, EXPERIMENTS, OUTLOOK = GROUPS

# --- parsing the model's reply -----------------------------------------------------------------


def test_parse_fields_accepts_common_label_styles() -> None:
    reply = (
        "Here is the summary.\n"
        "**Problem:** Fine-tuning is costly [1].\n"
        "- Key contribution: Low-rank adapters [2].\n"
        "They train few parameters [2].\n"
        "MOTIVATION: not mentioned in the passages"
    )
    fields = parse_fields(reply, OVERVIEW.fields)
    assert fields["problem"] == "Fine-tuning is costly [1]."
    # unlabelled lines continue the previous field; aliases map to our fields
    assert fields["contribution"] == "Low-rank adapters [2]. They train few parameters [2]."
    assert fields["motivation"] == NOT_REPORTED


def test_parse_fields_missing_fields_are_not_reported_and_lists_survive() -> None:
    reply = "RESULTS:\n- Within one point of full fine-tuning [3].\n- 60% less memory [4]."
    fields = parse_fields(reply, EXPERIMENTS.fields)
    assert (
        fields["results"] == "- Within one point of full fine-tuning [3].\n- 60% less memory [4]."
    )
    assert fields["dataset"] == fields["experiments"] == NOT_REPORTED


def test_parse_fields_ignores_labels_of_other_groups_and_unknown_labels() -> None:
    reply = "PROBLEM: Costly [1].\nNote: this is extra.\nMETHOD: Should not be read here."
    fields = parse_fields(reply, (PROBLEM,))
    # "Note:" is not a field, so it continues PROBLEM; METHOD isn't wanted, so it's text too
    assert fields["problem"].startswith("Costly [1]. Note: this is extra.")
    assert has_label("**Takeaway:** Remember this [1].", TAKEAWAY)
    assert not has_label("Remember this [1].", TAKEAWAY)


def test_validate_citations_with_explicit_allowed_numbers() -> None:
    check = validate_citations("A [3]. B [5]. C [4, 9].", 0, allowed={3, 4})
    assert check.text == "A [3]. B. C [4]."
    assert check.cited == [3, 4] and check.invalid == [5, 9]


# --- choosing passages -------------------------------------------------------------------------


def chunk(index: int, kind: str, text: str, title: str = "", chunk_kind: str = "text") -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        chunk_index=index,
        section_kind=kind,
        section_title=title or kind.title(),
        section_id=None,
        kind=chunk_kind,
        text=text,
        page_start=1,
        page_end=1,
        char_start=index * 100,
        boxes=[],
    )


def test_select_uses_matching_sections_with_leads_first_in_reading_order() -> None:
    chunks = [
        chunk(0, "abstract", "We match full fine-tuning within one point on four datasets."),
        chunk(1, "introduction", "Adapting models is expensive."),
        chunk(2, "experiments", "We evaluate on MedQA and CaseHOLD datasets.", "4 Experiments"),
        chunk(3, "experiments", "Baselines include full fine-tuning.", "4 Experiments"),
        chunk(4, "results", "Rank 8 is within one point of the baseline result.", "5 Results"),
        chunk(5, "references", "[1] Some dataset paper with results. 2020."),
    ]
    chosen = PaperPassages(chunks).select(EXPERIMENTS, token_budget=1000, max_passages=6)
    assert [c.chunk.chunk_index for c in chosen] == [0, 2, 3, 4]  # reading order
    reasons = {c.chunk.chunk_index: c.reason for c in chosen}
    assert reasons == {0: "lead", 2: "section_opening", 3: "topic_match", 4: "section_opening"}


def test_select_respects_budget_and_cap() -> None:
    long_text = "method approach model " * 200  # ~1100 tokens
    chunks = [
        chunk(0, "method", "We propose a method.", "3 Approach"),
        chunk(1, "method", long_text, "3 Approach"),
        chunk(2, "method", "The model freezes W.", "3 Approach"),
        chunk(3, "method", "Training objective.", "3 Approach"),
    ]
    chosen = PaperPassages(chunks).select(METHOD, token_budget=200, max_passages=2)
    assert len(chosen) == 2 and all(c.chunk.chunk_index != 1 for c in chosen)


def test_select_falls_back_to_the_whole_paper_without_headings() -> None:
    chunks = [
        chunk(0, "other", "Our model is evaluated on the SciQA dataset."),
        chunk(1, "other", "Unrelated acknowledgement of funding."),
    ]
    chosen = PaperPassages(chunks).select(EXPERIMENTS, token_budget=1000, max_passages=6)
    assert [(c.chunk.chunk_index, c.reason) for c in chosen] == [(0, "whole_paper")]
    nothing_matches = [chunk(0, "other", "Lorem ipsum dolor sit amet.")]
    chosen = PaperPassages(nothing_matches).select(OUTLOOK, 1000, 6)
    assert [c.reason for c in chosen] == ["paper_opening"]


# --- one field: citations + verification -------------------------------------------------------


def test_build_section_checks_statements_and_drops_foreign_citations() -> None:
    passages = {2: "Rank-8 adapters are within one point of full fine-tuning on all four datasets."}
    section, claims = build_section(
        RESULTS,
        "Rank-8 adapters are within one point of full fine-tuning [2][7].",
        passages,
        LexicalVerifier(),
    )
    assert section["citations"] == [2] and section["invalid_citations"] == [7]
    assert section["status"] == "supported" and section["label"] == "Well supported"
    assert claims and claims[0].status == "supported"

    section, claims = build_section(RESULTS, "not reported.", passages, LexicalVerifier())
    assert section["status"] == "not_reported" and section["text"] == NOT_REPORTED and not claims

    section, _ = build_section(
        RESULTS, "Quantum annealing doubles throughput [2].", passages, LexicalVerifier()
    )
    assert section["status"] == "unsupported"


def test_staleness_reasons() -> None:
    version = uuid.uuid4()
    settings = Settings(llm_provider="ollama", llm_model="qwen2.5:3b")
    document = SimpleNamespace(current_version_id=version)
    summary = SimpleNamespace(
        version_id=version,
        generation_config={"llm_provider": "ollama", "llm_model": "qwen2.5:3b",
                           "prompt_version": PROMPT_VERSION},
    )  # fmt: skip
    assert staleness(summary, document, settings) is None  # type: ignore[arg-type]
    summary.generation_config["llm_model"] = "llama3.1:8b"
    assert "llama3.1:8b" in staleness(summary, document, settings)  # type: ignore[arg-type,operator]
    document.current_version_id = uuid.uuid4()
    assert "earlier version" in staleness(summary, document, settings)  # type: ignore[arg-type,operator]


# --- end to end ----------------------------------------------------------------------------------


@pytest.fixture
async def lora(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> str:
    data = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return await upload(auth_client, settings, "l.pdf", data)


async def summarize(client: AsyncClient, settings: Settings, doc: str, **body: Any) -> Any:
    response = await client.post(f"/api/v1/documents/{doc}/summary", json=body or None)
    assert response.status_code == 202, response.text
    await get_dispatcher(settings).drain()
    return response.json()


async def get_summary(client: AsyncClient, doc: str) -> Any:
    response = await client.get(f"/api/v1/documents/{doc}/summary")
    assert response.status_code == 200, response.text
    return response.json()


async def summary_jobs(client: AsyncClient) -> list[dict[str, Any]]:
    jobs = (await client.get("/api/v1/jobs?limit=100")).json()["items"]
    return [j for j in jobs if j["kind"] == "paper.summarize"]


async def test_summary_is_generated_cited_and_verified(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    assert await get_summary(auth_client, lora) is None

    started = await summarize(auth_client, settings, lora)
    assert started["status"] == "queued" and started["sections"] == []

    summary = await get_summary(auth_client, lora)
    assert summary["status"] == "ready", summary["error_message"]
    assert [s["key"] for s in summary["sections"]] == [f.key for f in FIELDS]
    sources = {s["number"]: s for s in summary["sources"]}
    assert sources and sorted(sources) == list(range(1, len(sources) + 1))
    for source in sources.values():
        assert source["chunk_id"] and source["document"]["id"] == lora
        assert {"page_start", "boxes", "quote", "section_title", "reason"} <= set(source)

    by_key = {s["key"]: s for s in summary["sections"]}
    for section in summary["sections"]:
        assert set(section["citations"]) <= set(sources)  # only real passages are cited
        if section["status"] != "not_reported":
            assert section["citations"], section
    assert "60 percent" in by_key["results"]["text"] or "one point" in by_key["results"]["text"]
    assert by_key["limitations"]["status"] == "supported"
    assert by_key["takeaway"]["status"] != "not_reported"
    # The limitations come from the Limitations section, the results from the experiments group
    cited_sections = {sources[n]["section_title"] for n in by_key["limitations"]["citations"]}
    assert any("Limitations" in title for title in cited_sections)

    assert summary["support"]["status"] in {"supported", "partial"}
    assert summary["support"]["statements"] >= 5
    assert summary["generation_config"]["prompt_version"] == PROMPT_VERSION
    assert summary["generation_config"]["llm_model"] == FakeLLM.model_id
    assert [g["group"] for g in summary["trace"]["groups"]] == [
        "overview", "method", "experiments", "outlook", "takeaway",
    ]  # fmt: skip
    assert summary["output_tokens"] > 0 and summary["latency_ms"] > 0
    assert summary["stale"] is None and summary["progress"] is None


async def test_summary_is_cached_until_forced(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    first = await summarize(auth_client, settings, lora)
    again = await summarize(auth_client, settings, lora)
    assert again["id"] == first["id"] and again["status"] == "ready"
    assert len(await summary_jobs(auth_client)) == 1

    forced = await summarize(auth_client, settings, lora, force=True)
    assert forced["id"] != first["id"]
    latest = await get_summary(auth_client, lora)
    assert latest["id"] == forced["id"] and latest["status"] == "ready"
    assert len(await summary_jobs(auth_client)) == 2


async def test_summary_failure_is_saved_and_can_be_retried(
    auth_client: AsyncClient, settings: Settings, lora: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = FakeLLM.stream

    async def broken(self: FakeLLM, messages: Any, params: Any) -> Any:
        raise LLMError("Can't reach Ollama. Is it running?", detail="Start Ollama")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(FakeLLM, "stream", broken)
    await summarize(auth_client, settings, lora)
    failed = await get_summary(auth_client, lora)
    assert failed["status"] == "failed"
    assert failed["error_message"] == "Can't reach Ollama. Is it running?"
    assert failed["error_hint"] == "Start Ollama"
    job = (await summary_jobs(auth_client))[0]
    assert job["status"] == "failed" and job["error_message"] == failed["error_message"]

    monkeypatch.setattr(FakeLLM, "stream", original)
    retried = await summarize(auth_client, settings, lora)  # a failed summary isn't cached
    assert retried["id"] != failed["id"]
    assert (await get_summary(auth_client, lora))["status"] == "ready"


async def test_unavailable_model_is_refused_before_queueing(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    settings.llm_provider = "ollama"
    settings.ollama_base_url = "http://127.0.0.1:9"  # nothing listens here
    response = await auth_client.post(f"/api/v1/documents/{lora}/summary")
    assert response.status_code == 503
    error = response.json()["error"]
    assert "Ollama" in error["message"] and error["hint"]
    assert await summary_jobs(auth_client) == []


async def test_summaries_are_private_and_deleted_with_the_paper(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, lora: str
) -> None:
    await summarize(auth_client, settings, lora)
    own_token = auth_client.headers["Authorization"]
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.get(f"/api/v1/documents/{lora}/summary")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{lora}/summary")).status_code == 404

    client.headers["Authorization"] = own_token
    assert (await client.delete(f"/api/v1/documents/{lora}")).status_code == 204
    from sqlalchemy import func, select

    from app.core.database import get_session_factory
    from app.models.summary import PaperSummary

    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(PaperSummary)) == 0


async def test_papers_are_summarized_automatically_after_indexing(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    settings.summary_auto = True
    data = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    doc = await upload(auth_client, settings, "l.pdf", data)
    await get_dispatcher(settings).drain()
    jobs = (await auth_client.get("/api/v1/jobs?limit=10")).json()["items"]
    process = next(j for j in jobs if j["kind"] == "document.process")
    assert process["result"]["summary"] == "queued"
    assert (await get_summary(auth_client, doc))["status"] == "ready"


async def test_paper_without_headings_is_summarized_from_the_whole_text(
    auth_client: AsyncClient, settings: Settings
) -> None:
    text = (
        "Retrieval for question answering is costly when every passage must be read. "
        "We propose a hybrid retriever that fuses keyword and dense rankings.\n\n"
        "We evaluate the retriever on the SciQA dataset and compare it with BM25. "
        "The hybrid retriever improves recall by 12 percent over BM25.\n\n"
        "Our evaluation only covers English papers; future work should study other languages."
    )
    doc = await upload(auth_client, settings, "notes.txt", text.encode(), "text/plain")
    await summarize(auth_client, settings, doc)
    summary = await get_summary(auth_client, doc)
    assert summary["status"] == "ready", summary["error_message"]
    reasons = {p["reason"] for g in summary["trace"]["groups"] for p in g.get("passages", [])}
    assert reasons & {"whole_paper", "paper_opening"}
    assert any(s["status"] != "not_reported" for s in summary["sections"])


async def test_failed_regeneration_keeps_the_previous_summary(
    auth_client: AsyncClient, settings: Settings, lora: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = await summarize(auth_client, settings, lora)

    async def broken(self: FakeLLM, messages: Any, params: Any) -> Any:
        raise LLMError("The language model took too long to respond.")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(FakeLLM, "stream", broken)
    await summarize(auth_client, settings, lora, force=True)
    latest = await get_summary(auth_client, lora)
    assert latest["status"] == "failed"
    assert latest["previous"]["id"] == good["id"]
    assert latest["previous"]["status"] == "ready" and latest["previous"]["sections"]
    assert latest["previous"]["previous"] is None


def test_field_text_is_normalized_for_reading_and_checking() -> None:
    from app.services.summaries.engine import checkable_claims, normalize_text
    from app.services.summaries.spec import DATASET, METHOD

    # small models often lead with the marker; it moves to the end of the first sentence
    assert normalize_text(METHOD, "[4] The paper freezes W. Only A and B are trained.") == (
        "The paper freezes W [4]. Only A and B are trained."
    )
    assert normalize_text(TAKEAWAY, "Researchers should remember that adapters are cheap [2].") == (
        "Adapters are cheap [2]."
    )
    # an uncited sentence is covered by the nearest citation in the same field
    claims = checkable_claims(
        METHOD, "The paper freezes the weights. Only A and B are trained [4]."
    )
    assert [c.citations for c in claims] == [[4], [4]]
    # a bare list is checked as a statement about the field
    [fragment] = checkable_claims(DATASET, "MedQA, CaseHOLD, FiQA, SciQA-2400 [6]")
    assert fragment.text == "The datasets used are MedQA, CaseHOLD, FiQA, SciQA-2400."
    assert fragment.citations == [6]


def test_a_field_with_only_citations_is_not_reported() -> None:
    section, _ = build_section(PROBLEM, "[2]", {2: "Fine-tuning is expensive."}, LexicalVerifier())
    assert section["status"] == "not_reported"


def test_verifier_context_is_put_before_every_window() -> None:
    from app.services.rag.citations import Claim
    from app.services.rag.verify import verify_claims

    seen: list[str] = []

    class Recorder(LexicalVerifier):
        def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
            seen.extend(premise for premise, _ in pairs)
            return super().entailment(pairs)

    long_passage = " ".join(f"Sentence number {i} about adapters." for i in range(40))
    verify_claims(Recorder(), [Claim("Adapters are cheap.", [1])], {1: long_passage}, "LoRA paper")
    assert len(seen) > 1 and all(premise.startswith("LoRA paper. ") for premise in seen)


def test_repeated_citations_are_merged_and_framing_removed() -> None:
    from app.services.summaries.engine import normalize_text

    assert normalize_text(RESULTS, "Rank 8 matches it [7] [9] [6] [7] [9] [1].") == (
        "Rank 8 matches it [7][9][6][1]."
    )
    assert normalize_text(
        TAKEAWAY, "In one sentence, a researcher should remember that adapters are cheap [1]."
    ) == ("Adapters are cheap [1].")


async def test_generation_stops_when_the_model_loops_on_citations() -> None:
    from app.services.llm import GenerationParams, Message, StreamEvent
    from app.services.summaries.engine import complete

    closed = []

    class Looping:
        async def stream(self, messages: Any, params: Any) -> Any:
            try:
                yield StreamEvent(text="RESULTS: Rank 8 matches full fine-tuning ")
                for _ in range(500):
                    yield StreamEvent(text="[7] [9] ")
            finally:
                closed.append(True)

    result = await complete(Looping(), [Message("user", "x")], GenerationParams())  # type: ignore[arg-type]
    assert result.stopped_loop and closed == [True]
    assert result.text.count("[") < 20 and result.output_tokens > 0


async def test_fields_the_model_skipped_are_asked_for_once_more(
    auth_client: AsyncClient, settings: Settings, lora: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = FakeLLM.fill_fields
    prompts: list[str] = []

    def skips_future_work(self: FakeLLM, prompt: str) -> str:
        prompts.append(prompt)
        reply = original(self, prompt)
        if "LIMITATIONS:" in prompt.rsplit("Fields:", 1)[-1]:  # first outlook call only
            return "\n".join(line for line in reply.splitlines() if not line.startswith("FUTURE"))
        return reply

    monkeypatch.setattr(FakeLLM, "fill_fields", skips_future_work)
    await summarize(auth_client, settings, lora)
    summary = await get_summary(auth_client, lora)
    outlook = next(g for g in summary["trace"]["groups"] if g["group"] == "outlook")
    assert outlook["retry"]["fields"] == ["future_work"]
    future = next(s for s in summary["sections"] if s["key"] == "future_work")
    assert future["status"] != "not_reported" and "Future work" in future["text"]


def test_field_labels_used_as_citations_are_removed() -> None:
    from app.services.summaries.engine import normalize_text

    assert (
        normalize_text(TAKEAWAY, "Adapters save memory. [CONTRIBUTION]") == "Adapters save memory."
    )


def test_markers_inside_a_field_belong_to_their_sentence() -> None:
    from app.services.summaries.engine import normalize_text

    assert normalize_text(RESULTS, "Rank 8 matches it [6]. [7] Memory drops by 60 percent.") == (
        "Rank 8 matches it [6]. Memory drops by 60 percent [7]."
    )
    assert normalize_text(RESULTS, "Trained with a learning rate of 2e-5 [14]. [14]") == (
        "Trained with a learning rate of 2e-5 [14]."
    )


async def test_fields_answered_with_citations_only_are_asked_again(
    auth_client: AsyncClient, settings: Settings, lora: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.summaries.prompt import has_text

    assert not has_text("[3]") and not has_text("[3][4].") and has_text("Rank 8 works [3].")
    original = FakeLLM.fill_fields
    calls: list[str] = []

    def citation_only_method(self: FakeLLM, prompt: str) -> str:
        calls.append(prompt)
        reply = original(self, prompt)
        fields = prompt.rsplit("\nFields:\n", 1)[1].split("Answer format", 1)[0]
        if fields.startswith("METHOD:") and "ARCHITECTURE:" in fields:  # first method call
            return reply.replace(reply.split("\n")[0], "METHOD: [3]")
        return reply

    monkeypatch.setattr(FakeLLM, "fill_fields", citation_only_method)
    await summarize(auth_client, settings, lora)
    summary = await get_summary(auth_client, lora)
    method_group = next(g for g in summary["trace"]["groups"] if g["group"] == "method")
    assert method_group["retry"]["fields"] == ["method"]
    method = next(s for s in summary["sections"] if s["key"] == "method")
    assert method["status"] != "not_reported" and len(method["text"]) > 10


def test_not_reported_said_in_a_sentence() -> None:
    from app.services.summaries.prompt import is_not_reported

    assert is_not_reported("The compute is not reported in the provided passages. Not reported.")
    assert is_not_reported("The passages do not mention the hardware.")
    assert not is_not_reported("The paper does not report results on ImageNet [3].")  # cited fact
    assert not is_not_reported("Rank-8 adapters are within one point [2].")


def test_a_citation_dump_is_dropped() -> None:
    from app.services.summaries.engine import normalize_text
    from app.services.summaries.spec import CONTRIBUTION

    dump = "".join(f"[{n}]" for n in range(1, 19))
    assert normalize_text(CONTRIBUTION, f"Both papers aim to improve efficiency. {dump}") == (
        "Both papers aim to improve efficiency."
    )
    assert (
        normalize_text(CONTRIBUTION, "Adapters are cheap [1][2][3].")
        == "Adapters are cheap [1][2][3]."
    )


def test_a_label_repeated_inside_its_field_is_removed() -> None:
    reply = "PROBLEM: Dense encoders miss terms [10]. PROBLEM: It also limits fluency [10]."
    assert parse_fields(reply, (PROBLEM,))["problem"] == (
        "Dense encoders miss terms [10]. It also limits fluency [10]."
    )

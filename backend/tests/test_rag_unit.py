"""RAG building blocks: query analysis, citations, claims, context selection, verification, LLMs."""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.models.document import Chunk, Document
from app.services.llm import INSUFFICIENT, FakeLLM, GenerationParams, LLMError, Message
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compat import OpenAICompatibleProvider
from app.services.rag.citations import split_claims, validate_citations
from app.services.rag.context import select_context
from app.services.rag.prompt import build_messages, is_build_request, is_gpt_build_request
from app.services.rag.query import analyze_query
from app.services.rag.verify import LexicalVerifier, summarize, verify_claims
from app.services.retrieval.service import PassageResult

# --- query analysis ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Compare LoRA and prefix tuning", "comparison"),
        ("How does the hybrid retriever work?", "methodology_question"),
        ("Which datasets were used?", "dataset_search"),
        ("What are the limitations of this approach?", "research_gap"),
        ("Summarize the main contribution", "summarization"),
        ("What recall did the system reach?", "factual_question"),
    ],
)
def test_intent(question: str, intent: str) -> None:
    assert analyze_query(question).intent == intent


@pytest.mark.parametrize(
    ("question", "years"),
    [
        ("LoRA papers after 2023", (2024, None)),
        ("retrieval work since 2020", (2020, None)),
        ("methods before 2019", (None, 2018)),
        ("results published in 2024", (2024, 2024)),
        ("between 2021 and 2019 what changed", (2019, 2021)),
        ("what is BM25", (None, None)),
    ],
)
def test_temporal_filters_are_extracted_and_removed_from_the_query(
    question: str, years: tuple[int | None, int | None]
) -> None:
    analysis = analyze_query(question)
    assert (analysis.year_from, analysis.year_to) == years
    if years != (None, None):
        assert analysis.temporal_phrase and analysis.temporal_phrase not in analysis.retrieval_query
        assert analysis.notes
    else:
        assert analysis.retrieval_query == question


def test_entities_and_follow_ups() -> None:
    analysis = analyze_query('How does "reciprocal rank fusion" compare to BM25 and LoRA?')
    assert {"reciprocal rank fusion", "BM25", "LoRA"} <= set(analysis.entities)

    follow = analyze_query("What are its limitations?", previous_question="How does LoRA work?")
    assert follow.follow_up
    assert follow.retrieval_query.startswith("How does LoRA work?")
    standalone = analyze_query("How is BM25 computed?", previous_question="How does LoRA work?")
    assert not standalone.follow_up and standalone.retrieval_query == "How is BM25 computed?"


@pytest.mark.parametrize(
    ("question", "about"),
    [
        ("How does the proposed method work?", True),
        ("What is the main contribution of this paper?", True),
        ("What limitations do the authors mention?", True),
        ("Which datasets are used?", True),
        ("Why does Equation 2 divide the attention scores by the square root of d_k?", True),
        ("What does Figure 3 show?", True),
        ("Define BLEU in the context of the evaluation.", True),
        ("What is tanh?", True),
        ("Which experiments support the main claim?", True),
        ("Who won the 1998 football world cup final?", False),
        ("What is the boiling point of water?", False),
    ],
)
def test_questions_about_the_paper_itself_are_recognized(question: str, about: bool) -> None:
    assert analyze_query(question).about_the_paper is about


def test_short_technical_definition_is_classified_as_a_concept_question() -> None:
    analysis = analyze_query("What is tanh?")
    assert analysis.intent == "concept_explanation" and analysis.about_the_paper


# --- citations --------------------------------------------------------------------------------


def test_citations_are_validated_and_normalized() -> None:
    check = validate_citations("Fusion helps [1, 3]. Reranking adds more [2-4]. Invented [9].", 3)
    assert check.cited == [1, 3, 2]
    assert check.invalid == [4, 9]
    assert check.text == "Fusion helps [1][3]. Reranking adds more [2][3]. Invented."


@pytest.mark.parametrize(
    ("answer", "cleaned"),
    [
        # copied placeholders go, with the marker-only sentence they leave behind
        (
            "<statement from passage 1> [1]. Table 2 reports Recall@1000.",
            "Table 2 reports Recall@1000.",
        ),
        (
            "Fusion helps [1]. <statement from passage 2> [2]. Reranking adds more [3].",
            "Fusion helps [1]. Reranking adds more [3].",
        ),
        ("<passage 2> [2].", ""),
        # real content in brackets is unwrapped; comparisons and normal markers are untouched
        (
            "<4.1 points improvement reported in the paper> [2]",
            "4.1 points improvement reported in the paper [2]",
        ),
        ("Memory drops from >780GB to <48GB [1].", "Memory drops from >780GB to <48GB [1]."),
        ("Memory drops. [2] Accuracy is kept [3].", "Memory drops. [2] Accuracy is kept [3]."),
        ("If a<b and c>d then [1].", "If a<b and c>d then [1]."),
    ],
)
def test_copied_prompt_placeholders_are_removed(answer: str, cleaned: str) -> None:
    assert validate_citations(answer, 3).text == cleaned


def test_a_claim_hidden_in_a_long_window_gets_a_sentence_level_look() -> None:
    class SentenceOnly:
        """Like the small NLI model: misses a long claim inside a multi-sentence premise."""

        name = "sentence-only"

        def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
            return [(0.99 if premise.strip() == claim else 0.1, 0.0) for premise, claim in pairs]

    passage = (
        "That is tuned through the quantized weights. QLoRA reduces the memory needed to "
        "finetune a 65B model from 780GB to 48GB. This marks a shift in accessibility."
    )
    claims = split_claims(
        "QLoRA reduces the memory needed to finetune a 65B model from 780GB to 48GB [1]."
    )
    [result] = verify_claims(SentenceOnly(), claims, {1: passage})
    assert result.status == "supported" and result.entailment == 0.99


def test_claims_keep_their_citations() -> None:
    claims = split_claims(
        "Hybrid retrieval improves recall by 7.3 points [1]. Latency stays under 120 ms [2][3].\n"
        "- LoRA adapters train 0.4% of the parameters [4].\n- ok"
    )
    assert [(c.text, c.citations) for c in claims] == [
        ("Hybrid retrieval improves recall by 7.3 points.", [1]),
        ("Latency stays under 120 ms.", [2, 3]),
        ("LoRA adapters train 0.4% of the parameters.", [4]),
    ]


# --- context selection ------------------------------------------------------------------------


def _result(text: str, score: float, title: str = "Paper", kind: str = "rerank") -> PassageResult:
    document = Document(id=uuid.uuid4(), title=title, doc_type="pdf", year=2024)
    chunk = Chunk(
        id=uuid.uuid4(), text=text, section_title="Method", page_start=1, page_end=1,
        char_start=0, boxes=[], document_id=document.id,
    )  # fmt: skip
    return PassageResult(
        rank=1, chunk=chunk, document=document, metadata=None, score=score, score_kind=kind,
        matched_by=["bm25"], retriever_ranks={}, fused_rank=1, highlights=[], snippet=(0, 0),
    )  # fmt: skip


def test_context_selection_threshold_duplicates_diversity_budget() -> None:
    fusion = "The two ranked lists are fused with reciprocal rank fusion over all retrievers."
    results = [
        _result(fusion, 0.95, "Hybrid (PDF)"),
        _result(fusion, 0.94, "Hybrid (Markdown)"),  # same text from another upload
        _result("Rank fusion " + fusion, 0.93),  # near-identical
        _result("Low-rank adapters freeze pretrained weights and train two small matrices.", 0.6),
        _result("Irrelevant acknowledgements section thanking the reviewers.", 0.001),
    ]
    selection = select_context(results, token_budget=1000, max_passages=5, min_relevance=0.02)
    titles = [e.result.document.title for e in selection.evidence]
    assert titles == ["Hybrid (PDF)", "Paper"]
    assert [e.number for e in selection.evidence] == [1, 2]
    reasons = {d["document_title"]: d["reason"] for d in selection.decisions}
    assert "near-duplicate" in reasons["Hybrid (Markdown)"]
    assert "below" in next(d for d in selection.decisions if d["score"] == 0.001)["reason"]

    tight = select_context(results, token_budget=10, max_passages=5, min_relevance=0.02)
    assert len(tight.evidence) == 1  # the first passage is always kept
    assert any(d["reason"] == "token budget reached" for d in tight.decisions)


# --- verification -----------------------------------------------------------------------------


def test_verification_statuses_and_summary() -> None:
    passages = {
        1: "The hybrid system improves recall at ten by 7.3 points over the best single retriever.",
        2: "Adapters insert small bottleneck layers between transformer blocks.",
    }
    claims = split_claims(
        "The hybrid system improves recall at ten by 7.3 points [1]. "
        "Adapters insert bottleneck layers between blocks and reduce training memory [2]. "
        "Quantum annealing solves retrieval exactly [1]. "
        "This sentence cites nothing at all."
    )
    results = verify_claims(LexicalVerifier(), claims, passages)
    assert [r.status for r in results] == ["supported", "partial", "unsupported", "uncited"]
    summary = summarize(results, "lexical", insufficient=False)
    assert summary.status == "partial"
    assert summary.explanation.startswith("1 of 4 statements directly supported")

    all_good = summarize(results[:1], "lexical", insufficient=False)
    assert (all_good.status, all_good.label) == ("supported", "Well supported")
    assert summarize([], "x", insufficient=True).label == "Insufficient evidence"


# --- prompt + fake LLM ------------------------------------------------------------------------


async def test_fake_llm_answers_only_from_evidence_with_citations() -> None:
    evidence = [
        SimpleNamespace(number=1, result=_result("Reranking raises recall to 78.5 overall.", 1)),
        SimpleNamespace(number=2, result=_result("Adapters train 0.4 percent of the weights.", 1)),
    ]
    messages = build_messages("What recall does reranking reach?", evidence, [])  # type: ignore[arg-type]
    assert messages[0].role == "system" and "[1]" in messages[-1].content
    text = "".join([e.text async for e in FakeLLM().stream(messages, GenerationParams())])
    assert "78.5" in text and "[1]" in text
    nothing = build_messages("Who won the football match?", evidence, [])  # type: ignore[arg-type]
    answer = "".join([e.text async for e in FakeLLM().stream(nothing, GenerationParams())])
    assert answer == INSUFFICIENT


def test_paper_chat_prompt_teaches_equations_figures_and_reproduction() -> None:
    evidence = [SimpleNamespace(number=1, result=_result("The method uses scaled dot-product attention.", 1))]
    messages = build_messages(
        "Explain Equation 1 and how to reproduce the method.", evidence, [], paper_chat=True
    )  # type: ignore[arg-type]
    assert "one selected paper for context" in messages[0].content
    assert "name each symbol" in messages[0].content
    assert "missing details separately" in messages[0].content
    assert "provide a concrete first version now" in messages[0].content
    assert "Do not refuse because a task is complex" in messages[0].content


def test_general_chat_prompt_continues_build_requests_from_history() -> None:
    messages = build_messages(
        "Help me build it then",
        [],
        [("How to build GPT from scratch", "Start with data, architecture, and training.")],
    )
    assert messages[1].content == "How to build GPT from scratch"
    assert messages[2].content == "Start with data, architecture, and training."
    assert "continue from the project just discussed" in messages[0].content
    assert "include complete code" in messages[0].content
    assert "decoder-only causal transformer" in messages[0].content
    assert "first small, runnable version" in messages[-1].content
    assert "CausalSelfAttention" in messages[-1].content
    assert "Do not use nn.LSTM" in messages[-1].content
    assert "self.position_embedding = nn.Embedding(...)" in messages[-1].content
    assert "x = tokens[:, :-1] and y = tokens[:, 1:]" in messages[-1].content
    assert "if any is missing, fix the code" in messages[-1].content


def test_vague_build_follow_up_uses_the_previous_topic() -> None:
    history = [("How to build GPT from scratch", "Start with a tiny decoder-only model.")]
    assert is_build_request("Can you help me finish it?", history)
    assert is_build_request("Help me build it then", history)
    assert not is_build_request("What is attention?", history)
    assert not is_build_request("Help me build a weekly routine", [])
    assert is_gpt_build_request("Help me build it then", history)


# --- providers --------------------------------------------------------------------------------


async def _collect(provider: Any, params: GenerationParams | None = None) -> tuple[str, Any]:
    text, final = "", None
    async for event in provider.stream(
        [Message("user", "hi")], params or GenerationParams(50, 0.0)
    ):
        text += event.text
        final = event if event.done else final
    return text, final


async def test_ollama_streams_ndjson_and_reports_missing_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "missing":
            return httpx.Response(404, json={"error": "model not found"})
        expected = {"temperature": 0.0, "num_predict": 50}
        if "num_ctx" in body["options"]:
            expected["num_ctx"] = 8192
        assert body["options"] == expected
        lines = [
            {"message": {"content": "Hello"}, "done": False},
            {"message": {"content": " world"}, "done": False},
            {"message": {"content": ""}, "done": True, "prompt_eval_count": 7, "eval_count": 2},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    transport = httpx.MockTransport(handler)
    text, final = await _collect(OllamaProvider("qwen2.5:3b", transport=transport))
    assert text == "Hello world" and (final.usage.input_tokens, final.usage.output_tokens) == (7, 2)
    text, _ = await _collect(
        OllamaProvider("qwen2.5:3b", transport=transport),
        GenerationParams(50, 0.0, context_window=8192),
    )
    assert text == "Hello world"
    with pytest.raises(LLMError, match="isn't installed") as error:
        await _collect(OllamaProvider("missing", transport=transport))
    assert "ollama pull missing" in (error.value.detail or "")


async def test_ollama_unreachable_is_explained() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="Can't reach Ollama") as error:
        await _collect(OllamaProvider("m", transport=httpx.MockTransport(handler)))
    assert "ollama pull m" in (error.value.detail or "")  # tells the user how to fix it


async def test_openai_compatible_streams_sse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer key"
        chunks = [
            {"choices": [{"delta": {"content": "Hi"}}]},
            {"choices": [{"delta": {"content": " there"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        ]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body)

    provider = OpenAICompatibleProvider("gpt-x", "key", transport=httpx.MockTransport(handler))
    text, final = await _collect(provider)
    assert text == "Hi there" and final.stop_reason == "stop" and final.usage.output_tokens == 2


# --- fixes found with the real model (qwen2.5:3b + NLI) --------------------------------------------


def test_enumerations_after_a_colon_are_separate_claims() -> None:
    claims = split_claims(
        "The main contributions are threefold: First, they release a benchmark. "
        "Second, they analyze failures [2]."
    )
    assert [c.text for c in claims] == [
        "The main contributions are threefold:",
        "First, they release a benchmark.",
        "Second, they analyze failures.",
    ]
    assert split_claims("Recall improves: from 0.61 to 0.68 [1].")[0].citations == [1]  # no split


def test_prefix_style_citations_attach_to_the_following_sentence() -> None:
    claims = split_claims(
        "[3] Figure 1 shows that memory use drops by 60 percent. "
        "[5] Table 1 shows LoRA r=8 is within one point of full fine-tuning."
    )
    assert [c.citations for c in claims] == [[3], [5]]
    assert claims[1].text.startswith("Table 1 shows")
    # the usual style is unchanged
    usual = split_claims("Memory drops by 60 percent [3]. Accuracy stays within a point [5].")
    assert [c.citations for c in usual] == [[3], [5]]


class _KeywordVerifier:
    """Entails when both passage and claim contain the keyword (stands in for NLI)."""

    name = "keyword"

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.premises: list[str] = []

    def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        self.premises += [p for p, _ in pairs]
        return [(0.95 if self.keyword in p and self.keyword in h else 0.01, 0.0) for p, h in pairs]


def test_long_passages_are_checked_in_windows_so_late_evidence_counts() -> None:
    from app.services.rag.citations import Claim
    from app.services.rag.verify import WINDOW_WORDS, passage_windows

    filler = " ".join(
        f"Sentence {i} talks about retrieval quality in general terms." for i in range(60)
    )
    passage = f"{filler} Our contributions are threefold: a benchmark, an analysis and a baseline."
    windows = passage_windows(passage)
    assert len(windows) > 1 and all(len(w.split()) <= WINDOW_WORDS + 20 for w in windows)
    assert "threefold" in windows[-1]
    verifier = _KeywordVerifier("threefold")
    [result] = verify_claims(
        verifier, [Claim("The contributions are threefold.", [2])], {2: passage}
    )
    assert result.status == "supported" and result.best_passage == 2
    assert all(len(p.split()) < len(passage.split()) for p in verifier.premises)


def test_uncited_claims_report_where_they_are_supported() -> None:
    from app.services.rag.citations import Claim

    passages = {1: "Unrelated text about datasets.", 2: "The benchmark has 2,400 questions."}
    claims = [
        Claim("The benchmark has 2,400 questions.", []),
        Claim("The model was trained on Mars.", []),
    ]
    results = verify_claims(_KeywordVerifier("2,400"), claims, passages)
    assert results[0].status == "uncited" and results[0].found_in == 2
    assert results[1].status == "uncited" and results[1].found_in is None
    summary = summarize(results, "keyword", insufficient=False)
    assert summary.explanation == (
        "1 of 2 statements directly supported; 1 not supported by the passages; "
        "1 supported but missing a citation."
    )


def test_wrong_citations_are_detected() -> None:
    # Seen with qwen2.5:3b: it cited a figure caption for a number that is in the abstract.
    from app.services.rag.citations import Claim

    passages = {
        1: "Adapters reduce GPU memory by 60 percent.",
        2: "Figure 1: Peak GPU memory during training.",
    }
    claims = [Claim("Adapters reduce GPU memory by 60 percent.", [2])]
    [result] = verify_claims(_KeywordVerifier("60 percent"), claims, passages)
    assert result.status == "unsupported"  # by the passage it cites
    assert result.found_in == 1 and result.best_passage == 1
    summary = summarize([result], "keyword", insufficient=False)
    assert summary.status == "supported"  # the evidence is there; the citation is wrong
    assert "supported by a different passage than the one cited" in summary.explanation


# --- real NLI model (opt-in: RUN_MODEL_TESTS=1, downloads ~280 MB once) ---------------------------


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1")
def test_nli_verifier_separates_supported_from_contradicted_claims() -> None:
    from app.services.models.manager import ModelManager
    from app.services.rag.citations import Claim
    from app.services.rag.verify import NLIVerifier

    passage = (
        "Across four domain adaptation tasks, rank-8 adapters match full fine-tuning within one "
        "point while training 0.4 percent of the parameters and reducing GPU memory by 60 percent."
    )
    claims = [
        Claim("Adapters reduce GPU memory by 60 percent.", [1]),
        Claim("Low-rank adapters increase GPU memory use substantially.", [1]),
        Claim("The adapters were evaluated on image segmentation benchmarks.", [1]),
    ]
    verifier = NLIVerifier("cross-encoder/nli-deberta-v3-xsmall", ModelManager(), "cpu")
    statuses = [r.status for r in verify_claims(verifier, claims, {1: passage})]
    assert statuses[0] == "supported"
    assert statuses[1] == "unsupported"
    assert statuses[2] != "supported"


def test_claims_split_at_a_citation_followed_by_a_new_sentence() -> None:
    # qwen2.5:3b sometimes drops the full stop: "… datasets [6] Adapters cut memory … [7]"
    claims = split_claims(
        "Rank 8 matches full fine-tuning on all datasets [6] Memory drops by 60% [7]"
    )
    assert [(c.text, c.citations) for c in claims] == [
        ("Rank 8 matches full fine-tuning on all datasets", [6]),
        ("Memory drops by 60%", [7]),
    ]
    # a citation inside a sentence is not a boundary
    assert len(split_claims("As reported in [3] the adapters are cheap to train.")) == 1

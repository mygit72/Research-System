"""Research chat end to end: SSE answer stream, citations, verification, persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.llm import FakeLLM, LLMError, StreamEvent, Usage
from app.services.rag.prompt import PROMPT_VERSION
from tests.conftest import register
from tests.test_code_review import VALID_GPT
from tests.test_indexing_api import upload


@pytest.fixture
async def library(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    retrieval = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    lora = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return {
        "retrieval": await upload(auth_client, settings, "r.pdf", retrieval),
        "lora": await upload(auth_client, settings, "l.pdf", lora),
    }


async def new_conversation(client: AsyncClient, **body: Any) -> str:
    response = await client.post("/api/v1/chat/conversations", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def ask(client: AsyncClient, conversation: str, question: str) -> list[dict[str, Any]]:
    response = await client.post(
        f"/api/v1/chat/conversations/{conversation}/messages", json={"content": question}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def of(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind]


async def test_answer_streams_with_valid_citations_and_verification(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "How much GPU memory do low-rank adapters save?")

    stages = [e["stage"] for e in of(events, "status")]
    assert stages == ["understanding", "searching", "reading", "writing", "verifying"]
    assert of(events, "query")[0]["analysis"]["intent"] in {
        "factual_question",
        "methodology_question",
    }
    evidence = of(events, "evidence")[0]["items"]
    assert evidence and evidence[0]["number"] == 1
    assert {"chunk_id", "document", "page_start", "boxes", "quote"} <= set(evidence[0])

    streamed = "".join(e["text"] for e in of(events, "token"))
    answer = of(events, "answer")[0]
    assert answer["text"] == streamed.strip()  # fake model only cites real passages
    assert answer["cited"] and answer["invalid_citations"] == []
    assert "60" in answer["text"]  # "reducing GPU memory by 60 percent"
    cited_doc = evidence[answer["cited"][0] - 1]["document"]["id"]
    assert cited_doc == library["lora"]

    verification = of(events, "verification")[0]
    assert verification["status"] == "supported" and verification["claims"]
    done = of(events, "done")[0]
    assert done["usage"]["output_tokens"] > 0 and "first_token" in done["timings_ms"]

    detail = (await auth_client.get(f"/api/v1/chat/conversations/{conversation}")).json()
    assert detail["title"].startswith("How much GPU memory")
    user, assistant = detail["messages"]
    assert (user["role"], assistant["role"]) == ("user", "assistant")
    assert assistant["id"] == done["message_id"] and assistant["status"] == "complete"
    assert assistant["content"] == answer["text"]
    assert assistant["support"]["status"] == "supported"
    assert assistant["generation_config"]["llm_model"] == FakeLLM.model_id
    assert assistant["generation_config"]["prompt_version"] == PROMPT_VERSION
    trace = assistant["retrieval_trace"]
    assert {"query", "search", "context"} <= set(trace)
    assert any(d["outcome"] == "used" for d in trace["context"]["decisions"])
    citations = assistant["citations"]
    assert [c["number"] for c in citations] == list(range(1, len(evidence) + 1))
    cited = [c for c in citations if c["cited"]]
    assert cited and all(c["support_status"] for c in cited)
    assert cited[0]["quote"] and cited[0]["page_start"] >= 1


async def test_general_question_without_matching_passages_uses_the_model(
    auth_client: AsyncClient,
    library: dict[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Passages the reranker scores below the floor never reach the model. (The floor is
    # calibrated for cross-encoder probabilities; the test reranker needs a higher one.)
    settings.reranker_provider, settings.context_min_relevance = "lexical", 0.5
    calls: list[int] = []
    original = FakeLLM.answer

    def general_answer(self: FakeLLM, prompt: str) -> str:
        calls.append(1)
        if "Who won the 1998 football world cup final?" in prompt:
            return (
                "**General background (not grounded in indexed papers):**\n\n"
                "This question can still be answered by the configured language model."
            )
        return original(self, prompt)

    monkeypatch.setattr(FakeLLM, "answer", general_answer)
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "Who won the 1998 football world cup final?")
    answer = of(events, "answer")[0]["text"]
    assert answer.startswith("**General background (not grounded in indexed papers):**")
    assert "configured language model" in answer
    assert "writing" in [e["stage"] for e in of(events, "status")]
    assert calls == [1]
    assert of(events, "verification") == []
    assert of(events, "evidence")[0]["items"] == []


async def test_empty_library_answers_general_question_with_model(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = FakeLLM.answer

    def general_answer(self: FakeLLM, prompt: str) -> str:
        calls.append(prompt)
        if "What is reciprocal rank fusion?" in prompt:
            return (
                "**General background (not grounded in indexed papers):**\n\n"
                "Reciprocal rank fusion combines ranked result lists using each result's position."
            )
        return original(self, prompt)

    monkeypatch.setattr(FakeLLM, "answer", general_answer)
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "What is reciprocal rank fusion?")
    assert of(events, "evidence")[0]["items"] == []
    answer = of(events, "answer")[0]["text"]
    assert answer.startswith("**General background (not grounded in indexed papers):**")
    assert "combines ranked result lists" in answer
    assert "writing" in [e["stage"] for e in of(events, "status")]
    assert calls


async def test_paper_chat_answers_general_question_without_passages(
    auth_client: AsyncClient,
    library: dict[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.rag.context import ContextSelection

    monkeypatch.setattr(
        "app.services.rag.pipeline.select_context",
        lambda *args, **kwargs: ContextSelection(evidence=[], decisions=[], tokens=0),
    )
    calls: list[str] = []
    original = FakeLLM.answer

    def general_answer(self: FakeLLM, prompt: str) -> str:
        calls.append(prompt)
        if "Answer ordinary general questions directly" in prompt:
            return (
                "**General background (not grounded in the selected paper)**\n\n"
                "A transformer uses attention layers to process relationships between tokens."
            )
        return original(self, prompt)

    monkeypatch.setattr(FakeLLM, "answer", general_answer)
    conversation = await new_conversation(auth_client, document_ids=[library["retrieval"]])
    events = await ask(auth_client, conversation, "How can I build a simple GPT?")

    answer = of(events, "answer")[0]["text"]
    assert not of(events, "evidence")[0]["items"]
    assert answer.startswith("**General background (not grounded in the selected paper)**")
    assert "transformer uses attention" in answer
    assert "writing" in [e["stage"] for e in of(events, "status")]
    assert calls and "How can I build a simple GPT?" in calls[0]


async def test_paper_chat_only_uses_that_paper(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    conversation = await new_conversation(auth_client, document_ids=[library["retrieval"]])
    events = await ask(auth_client, conversation, "How much memory and latency does it save?")
    documents = {item["document"]["id"] for item in of(events, "evidence")[0]["items"]}
    assert documents == {library["retrieval"]}
    listed = (
        await auth_client.get(f"/api/v1/chat/conversations?document_id={library['retrieval']}")
    ).json()
    assert [c["id"] for c in listed["items"]] == [conversation]
    assert listed["items"][0]["scope"] == "papers"

    await new_conversation(
        auth_client, document_ids=[library["retrieval"], library["lora"]]
    )
    paper_only = (
        await auth_client.get(
            f"/api/v1/chat/conversations?document_id={library['retrieval']}&single_paper=true"
        )
    ).json()
    assert [c["id"] for c in paper_only["items"]] == [conversation]


async def test_gpt_code_request_repairs_an_incomplete_first_draft(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DraftThenRepair:
        name = "ollama"
        model_id = "test-coder"
        is_remote = False

        def __init__(self) -> None:
            self.calls: list[tuple[list[Any], Any]] = []

        async def stream(self, messages: list[Any], params: Any) -> Any:
            self.calls.append((messages, params))
            response = (
                '```python\nprint("hello")\n```'
                if len(self.calls) == 1
                else VALID_GPT
            )
            yield StreamEvent(
                text=response,
                done=True,
                usage=Usage(input_tokens=10, output_tokens=20),
                model=self.model_id,
            )

    coder = DraftThenRepair()
    monkeypatch.setattr("app.services.rag.pipeline.get_coding_llm", lambda *args: coder)
    conversation = await new_conversation(auth_client)

    events = await ask(auth_client, conversation, "Build a GPT from scratch.")

    answer = of(events, "answer")[0]["text"]
    assert len(coder.calls) == 2
    assert coder.calls[0][1].max_tokens >= 4096
    assert coder.calls[0][1].context_window == 8192
    assert "static code review found these problems" in coder.calls[1][0][-1].content
    assert "Reviewing and correcting the code" in [e["detail"] for e in of(events, "status")]
    assert "Python syntax and the requested GPT structure passed static checks" in answer
    assert "Remaining issues" not in answer
    detail = (await auth_client.get(f"/api/v1/chat/conversations/{conversation}")).json()
    assert detail["messages"][-1]["generation_config"]["llm_model"] == "test-coder"


async def test_gpt_code_request_stops_after_two_unsuccessful_repairs(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StillIncomplete:
        name = "ollama"
        model_id = "test-coder"
        is_remote = False

        def __init__(self) -> None:
            self.responses = [
                '```python\nprint("draft")\n```',
                "```python\nclass CausalSelfAttention:\n    pass\n```\n# first repair",
                "```python\nclass CausalSelfAttention:\n    pass\n```\n# second repair",
            ]
            self.calls = 0

        async def stream(self, messages: list[Any], params: Any) -> Any:
            response = self.responses[self.calls]
            self.calls += 1
            yield StreamEvent(
                text=response,
                done=True,
                usage=Usage(input_tokens=10, output_tokens=20),
                model=self.model_id,
            )

    coder = StillIncomplete()
    monkeypatch.setattr("app.services.rag.pipeline.get_coding_llm", lambda *args: coder)
    conversation = await new_conversation(auth_client)

    events = await ask(auth_client, conversation, "Build a GPT from scratch.")

    answer = of(events, "answer")[0]["text"]
    assert coder.calls == 3  # one draft and no more than two repair attempts
    assert len([e for e in of(events, "status") if "Reviewing" in e["detail"]]) == 2
    assert "Code review note" in answer and "Treat it as unverified" in answer


async def test_follow_up_uses_the_previous_question(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    conversation = await new_conversation(auth_client)
    await ask(auth_client, conversation, "How do low-rank adapters work?")
    events = await ask(auth_client, conversation, "What are their limitations?")
    analysis = of(events, "query")[0]["analysis"]
    assert analysis["follow_up"] and "low-rank adapters" in analysis["retrieval_query"]


async def test_year_filter_from_the_question(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "What did papers after 2023 find about recall?")
    analysis = of(events, "query")[0]["analysis"]
    assert analysis["year_from"] == 2024
    documents = {item["document"]["id"] for item in of(events, "evidence")[0]["items"]}
    assert documents == {library["retrieval"]}


async def test_llm_failure_is_reported_and_saved(
    auth_client: AsyncClient, library: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: FakeLLM, messages: Any, params: Any) -> Any:
        raise LLMError("Can't reach Ollama. Is it running?", detail="connection refused")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(FakeLLM, "stream", broken)
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "How do low-rank adapters reduce memory?")
    error = of(events, "error")[0]
    assert error["message"] == "Can't reach Ollama. Is it running?"
    assert error["hint"] == "connection refused"
    detail = (await auth_client.get(f"/api/v1/chat/conversations/{conversation}")).json()
    assert detail["messages"][-1]["status"] == "error"
    assert detail["messages"][-1]["error"] == error["message"]


async def test_remote_llm_refused_in_local_only_mode(
    auth_client: AsyncClient, library: dict[str, str], settings: Settings
) -> None:
    settings.llm_provider, settings.llm_model, settings.local_only = "openai", "gpt-x", True
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "How do low-rank adapters reduce memory?")
    assert "LOCAL_ONLY" in of(events, "error")[0]["message"]


async def test_conversations_are_private_and_manageable(
    client: AsyncClient, auth_client: AsyncClient, library: dict[str, str]
) -> None:
    conversation = await new_conversation(auth_client, title="Adapters")
    renamed = await auth_client.patch(
        f"/api/v1/chat/conversations/{conversation}", json={"title": "LoRA notes"}
    )
    assert renamed.json()["title"] == "LoRA notes"
    bad = await auth_client.post(
        "/api/v1/chat/conversations",
        json={"document_ids": [library["lora"], library["lora"][:-4] + "0000"]},
    )
    assert bad.status_code == 422

    other = await register(client, "intruder@example.com")
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    for response in (
        await client.get(f"/api/v1/chat/conversations/{conversation}"),
        await client.post(
            f"/api/v1/chat/conversations/{conversation}/messages", json={"content": "hi"}
        ),
        await client.delete(f"/api/v1/chat/conversations/{conversation}"),
    ):
        assert response.status_code == 404
    assert (await client.get("/api/v1/chat/conversations")).json()["total"] == 0
    stolen = await client.post(
        "/api/v1/chat/conversations", json={"document_ids": [library["lora"]]}
    )
    assert stolen.status_code == 422  # can't scope a chat to someone else's paper


async def test_ai_status_reports_language_model_readiness(
    auth_client: AsyncClient, settings: Settings
) -> None:
    llm = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert llm == {
        "provider": "fake",
        "model": FakeLLM.model_id,
        "remote": False,
        "source": "server",
        "ready": True,
    }

    settings.llm_provider, settings.llm_model = "ollama", ""
    settings.ollama_base_url = "http://127.0.0.1:9"  # nothing listens here
    llm = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert llm["model"] == "qwen2.5:3b" and llm["ready"] is False
    assert "ollama pull qwen2.5:3b" in llm["hint"]

    settings.llm_provider = "openai"
    llm = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert llm["remote"] and llm["problem"] == "OPENAI_API_KEY is not configured."


async def test_general_questions_in_paper_chat_still_find_evidence(
    auth_client: AsyncClient,
    library: dict[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A floor above every score mimics the cross-encoder on "what is the main contribution?"
    # (no shared words, ~0 for every passage); in a paper's chat it still gets passages.
    settings.reranker_provider, settings.context_min_relevance = "lexical", 0.99
    original = FakeLLM.answer

    def general_answer(self: FakeLLM, prompt: str) -> str:
        if "Who won the 1998 football world cup final?" in prompt:
            return (
                "**General background (not grounded in the selected paper):**\n\n"
                "This question can still be answered by the configured language model."
            )
        return original(self, prompt)

    monkeypatch.setattr(FakeLLM, "answer", general_answer)
    paper_chat = await new_conversation(auth_client, document_ids=[library["lora"]])
    events = await ask(auth_client, paper_chat, "What is the main contribution of this paper?")
    assert of(events, "query")[0]["analysis"]["about_the_paper"]
    saved = (await auth_client.get(f"/api/v1/chat/conversations/{paper_chat}")).json()
    notes = saved["messages"][-1]["retrieval_trace"]["query"]["notes"]
    assert any("without the reranker" in note for note in notes)
    items = of(events, "evidence")[0]["items"]
    assert items and {i["document"]["id"] for i in items} == {library["lora"]}

    # General questions in paper chat are answered without attributing them to the paper.
    events = await ask(auth_client, paper_chat, "Who won the 1998 football world cup final?")
    assert of(events, "evidence")[0]["items"] == []
    answer = of(events, "answer")[0]["text"]
    assert answer.startswith("**General background (not grounded in the selected paper):**")
    assert "configured language model" in answer

    # In library chat the floor applies as usual.
    library_chat = await new_conversation(auth_client)
    events = await ask(auth_client, library_chat, "What is the main contribution of this paper?")
    assert of(events, "evidence")[0]["items"] == []


async def test_one_user_cannot_start_too_many_answers_at_once(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    from app.api.routes import chat as chat_routes

    settings.chat_max_concurrent_per_user = 1
    conversation = await new_conversation(auth_client)
    await ask(auth_client, conversation, "How much GPU memory do adapters save?")
    assert chat_routes._answering == {}  # released when the answer finished

    me = (await auth_client.get("/api/v1/users/me")).json()["id"]
    import uuid as uuid_module

    chat_routes._answering[uuid_module.UUID(me)] = 1  # an answer is still streaming
    try:
        busy = await auth_client.post(
            f"/api/v1/chat/conversations/{conversation}/messages", json={"content": "And memory?"}
        )
        assert busy.status_code == 429
        assert busy.json()["error"]["message"] == "You already have answers being written."
    finally:
        chat_routes._answering.clear()

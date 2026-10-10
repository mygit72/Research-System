"""Semantic answer cache: reuse only for the same passages and a near-identical first question."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.rag.answer_cache import key_tokens, same_key_tokens
from tests.test_chat_api import ask, new_conversation, of
from tests.test_indexing_api import upload

API = "/api/v1"


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        # measured near-misses with high cosine: the key tokens tell them apart
        ("Does DPR outperform BM25?", "Does BM25 outperform DPR?", False),
        ("Which models are compared in Table 2?", "Which models are compared in Table 3?", False),
        ("How much GPU memory does QLoRA need for a 65B model?",
         "How much GPU memory does QLoRA need for a 33B model?", False),
        ("How much memory does QLoRA save?", "How much memory does LoRA save?", False),
        ("How does BM25 perform on Natural Questions?", "How does BM25 perform on TriviaQA?", False),
        # paraphrases keep them
        ("What datasets does RALA use for evaluation?", "Which datasets is RALA evaluated on?", True),
        ("How are BM25 and dense rankings combined?", "how are bm25 and dense rankings combined", True),
        ("What are the limitations of RAG?", "What limitations does RAG have?", True),
        ("How much GPU memory does QLoRA save?", "how much gpu memory does qlora save", True),
    ],
)  # fmt: skip
def test_key_tokens_are_numbers_and_names_in_order(a: str, b: str, same: bool) -> None:
    assert same_key_tokens(a, b) is same
    assert "what" not in key_tokens(a) and "how" not in key_tokens(a)


@pytest.fixture
async def lora(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> str:
    data = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return await upload(auth_client, settings, "l.pdf", data)


async def chat_calls(client: AsyncClient) -> int:
    usage = (await client.get(f"{API}/usage")).json()
    return sum(f["calls"] for f in usage["by_feature"] if f["feature"] == "chat")


async def test_a_near_identical_first_question_reuses_the_answer(
    auth_client: AsyncClient, lora: str
) -> None:
    question = "How much GPU memory do low-rank adapters save?"
    first = await ask(auth_client, await new_conversation(auth_client), question)
    assert not of(first, "reused") and await chat_calls(auth_client) == 1

    conversation = await new_conversation(auth_client)
    again = await ask(auth_client, conversation, question.lower() + "  ")
    [reused] = of(again, "reused")
    assert reused["question"] == question and reused["similarity"] >= 0.95
    assert reused["asked_at"].endswith("+00:00")  # read as UTC by the browser
    stages = [e["stage"] for e in of(again, "status")]
    assert "writing" not in stages and "verifying" not in stages and "reusing" in stages
    assert of(again, "answer")[0]["text"] == of(first, "answer")[0]["text"]
    assert of(again, "verification")[0]["status"] == of(first, "verification")[0]["status"]
    assert await chat_calls(auth_client) == 1  # the model wasn't called again

    done = of(again, "done")[0]
    saved = (await auth_client.get(f"{API}/chat/conversations/{conversation}")).json()
    message = next(m for m in saved["messages"] if m["id"] == done["message_id"])
    assert message["generation_config"]["reused_from"]["question"] == question
    assert any(c["cited"] for c in message["citations"])  # citations saved as for a new answer


async def test_no_reuse_for_other_numbers_follow_ups_or_fresh(
    auth_client: AsyncClient, lora: str
) -> None:
    question = "What accuracy do rank-8 adapters reach on GLUE?"
    conversation = await new_conversation(auth_client)
    await ask(auth_client, conversation, question)
    other = await ask(
        auth_client,
        await new_conversation(auth_client),
        "What accuracy do rank-16 adapters reach on GLUE?",
    )
    assert not of(other, "reused")
    follow_up = await ask(auth_client, conversation, question)  # has history now
    assert not of(follow_up, "reused")
    response = await auth_client.post(
        f"{API}/chat/conversations/{await new_conversation(auth_client)}/messages",
        json={"content": question, "fresh": True},
    )
    assert '"type": "reused"' not in response.text
    assert await chat_calls(auth_client) == 4


async def test_reuse_can_be_turned_off(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    settings.answer_cache_enabled = False
    question = "How much GPU memory do low-rank adapters save?"
    await ask(auth_client, await new_conversation(auth_client), question)
    again = await ask(auth_client, await new_conversation(auth_client), question)
    assert not of(again, "reused")


async def test_reuse_keeps_the_earlier_numbering_when_passages_come_back_reordered(
    auth_client: AsyncClient, lora: str
) -> None:
    import uuid as uuid_module

    from sqlalchemy import select

    from app.core.database import get_session_factory
    from app.models.chat import Citation

    question = "How much GPU memory do low-rank adapters save?"
    first = await ask(auth_client, await new_conversation(auth_client), question)
    message_id = uuid_module.UUID(of(first, "done")[0]["message_id"])
    async with get_session_factory()() as session:  # as if the earlier ranking had 1 and 2 swapped
        rows = (
            (await session.execute(select(Citation).where(Citation.message_id == message_id)))
            .scalars()
            .all()
        )
        by_number = {c.number: c for c in rows}
        assert len(by_number) >= 2
        by_number[1].number, by_number[2].number = 2, 1
        await session.commit()
        earlier_order = [c.chunk_id for c in sorted(rows, key=lambda c: c.number)]

    again = await ask(auth_client, await new_conversation(auth_client), question)
    assert of(again, "reused")
    shown = of(again, "evidence")[-1]["items"]  # re-sent in the earlier answer's order
    assert [uuid_module.UUID(i["chunk_id"]) for i in shown] == earlier_order
    assert [i["number"] for i in shown] == list(range(1, len(shown) + 1))


async def test_an_answer_that_failed_its_check_is_not_reused(
    auth_client: AsyncClient, lora: str
) -> None:
    import uuid as uuid_module

    from app.core.database import get_session_factory
    from app.models.chat import ChatMessage

    question = "How much GPU memory do low-rank adapters save?"
    first = await ask(auth_client, await new_conversation(auth_client), question)
    async with get_session_factory()() as session:
        message = await session.get(
            ChatMessage, uuid_module.UUID(of(first, "done")[0]["message_id"])
        )
        assert message is not None and message.support is not None
        message.support = {**message.support, "status": "unsupported"}
        await session.commit()
    again = await ask(auth_client, await new_conversation(auth_client), question)
    assert not of(again, "reused")

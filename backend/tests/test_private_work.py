"""What a user reads, asks and writes stays theirs: it isn't written to the server's logs.

(That another account — an administrator's included — can't reach it through the API is
tested for every route in test_tenant_isolation.py.)
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import structlog
from httpx import AsyncClient

from app.core.config import BACKEND_ROOT, Settings
from app.demo import sample_papers as sp
from app.services.llm import FakeLLM, LLMError
from app.workers.dispatcher import get_dispatcher
from tests.test_chat_api import ask, new_conversation, of
from tests.test_indexing_api import upload

API = "/api/v1"


def _forget_cached_loggers() -> None:
    """Module-level loggers keep the configuration they were first used with."""
    for name, module in list(sys.modules.items()):
        logger = getattr(module, "log", None) if name.startswith("app.") else None
        if type(logger).__name__ == "BoundLoggerLazyProxy":
            vars(logger).pop("bind", None)


@contextmanager
def every_log_line() -> Iterator[list[dict[str, Any]]]:
    """Everything the app logs, at every level (the test settings only print warnings)."""
    lines: list[dict[str, Any]] = []

    def capture(_logger: object, level: str, event: dict[str, Any]) -> dict[str, Any]:
        lines.append({**event, "level": level})
        raise structlog.DropEvent

    saved = structlog.get_config()
    _forget_cached_loggers()
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, capture],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=False,
    )
    try:
        yield lines
    finally:
        structlog.configure(**saved)
        _forget_cached_loggers()


async def test_logs_never_contain_what_a_user_reads_asks_or_writes(
    client: AsyncClient,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = "How much GPU memory do low-rank adapters save in practice?"
    note = "My private thought: compare this with our own unpublished results."
    email, name = "private.person@example.com", "Priya Private"
    with every_log_line() as lines:
        registered = await client.post(
            f"{API}/auth/register",
            json={"email": email, "password": "correct-horse-42", "full_name": name},
        )
        client.headers["Authorization"] = f"Bearer {registered.json()['access_token']}"
        paper = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "confidential-draft.pdf")
        document = await upload(client, settings, "confidential-draft.pdf", paper.read_bytes())
        created = await client.post(f"{API}/notes", json={"content": note, "document_id": document})
        assert created.status_code == 201, created.text
        listed = await client.get(f"{API}/documents", params={"q": "low-rank secret-filter"})
        assert listed.status_code == 200

        conversation = await new_conversation(client)
        answer = of(await ask(client, conversation, question), "answer")[0]["text"]
        summary = await client.post(f"{API}/documents/{document}/summary")
        assert summary.status_code in (200, 202), summary.text
        await get_dispatcher(settings).drain()

        def fail(*args: Any, **kwargs: Any) -> str:
            raise LLMError("The language model service is busy.", detail="HTTP 429")

        monkeypatch.setattr(FakeLLM, "answer", fail)  # the failure path logs too
        failed = await ask(client, conversation, question + " And the training time?")
        assert of(failed, "error")

    events = {line["event"] for line in lines}
    assert {"request", "user_registered", "document_processed", "answer_failed"} <= events
    logged = json.dumps(lines, default=str).lower()
    private = {
        "the question": question,
        "the answer": answer,
        "the note": note,
        "the paper's title": sp.LORA_PAPER.title,
        "the paper's text": "reducing GPU memory by 60 percent",
        "an author": sp.LORA_PAPER.authors[0],
        "the file name": "confidential-draft",
        "the library filter": "secret-filter",
        "the email": email,
        "the name": name,
    }
    leaked = [what for what, text in private.items() if text.lower() in logged]
    assert not leaked, f"written to the logs: {leaked}"


def test_the_web_servers_access_log_leaves_out_query_strings() -> None:
    """Library filters and graph searches travel in the query string (`?q=…`), and so do the
    signatures of file links: the bundled nginx must log the path only."""
    config = (BACKEND_ROOT.parent / "infra" / "docker" / "nginx.conf").read_text(encoding="utf-8")
    formats = dict(re.findall(r"log_format\s+(\w+)\s+([^;]+);", config))
    used = re.findall(r"access_log\s+\S+\s+(\w+)\s*;", config)
    assert used and set(used) <= set(formats), "every access_log names a format defined here"
    for name in used:
        assert "$uri" in formats[name]
        assert not re.search(
            r"\$(request|request_uri|args|query_string|http_referer)\b", formats[name]
        )
    # No `server` or `location` falls back to nginx's default format, which has the query.
    assert len(used) == len(re.findall(r"access_log\s", config))

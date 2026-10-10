"""The site's shared free model (FREE_TIER): opt-in, a daily allowance, pacing, retries.

The hosted model is never called: "OpenRouter" here is a stand-in server on 127.0.0.1 that
speaks the OpenAI streaming format and records what it was sent.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import get_session_factory
from app.models.model_choice import UserModelChoice
from app.models.usage import LLMUsage
from app.services.llm import free_tier
from app.services.llm.base import GenerationParams, LLMError, Message
from app.services.llm.openai_compat import OpenAICompatibleProvider
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_chat_api import ask, library, new_conversation, of  # noqa: F401 - fixture
from tests.test_indexing_api import upload
from tests.test_starter_generation import FakeServer, ollama_reply, server  # noqa: F401 - fixture

API = "/api/v1/users/me/model"
SITE_KEY = "sk-or-v1-the-sites-own-key-0000"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
QUESTION = "How much GPU memory do low-rank adapters save?"
ANSWER = "Low-rank adapters cut GPU memory by 60 percent [1]."
Reply = tuple[int, str, dict[str, str]]


def sse(text: str) -> Reply:
    chunks: list[dict[str, Any]] = [
        {"choices": [{"delta": {"content": text}}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 9},
        },
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return 200, body, {"Content-Type": "text/event-stream"}


def busy(retry_after: str = "0") -> Reply:
    return (
        429,
        json.dumps({"error": {"message": "Rate limit exceeded"}}),
        {"Retry-After": retry_after},
    )


class Upstream:
    """A stand-in hosted model: records each request, answers with `respond(body)`."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.respond: Callable[[dict[str, Any]], Reply] = lambda body: sse(ANSWER)
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                upstream.requests.append(
                    {"path": self.path, "headers": dict(self.headers.items()), "body": body}
                )
                status, text, headers = upstream.respond(body)
                payload = text.encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def upstream(settings: Settings) -> Iterator[Upstream]:
    """The settings of a public site whose model is a shared free one."""
    fake = Upstream()
    settings.llm_provider, settings.llm_model = "openai", MODEL
    settings.llm_api_base, settings.openai_api_key = fake.url, SecretStr(SITE_KEY)
    settings.free_tier = True
    settings.free_tier_requests_per_minute = 0  # no pacing: it has its own test
    settings.free_tier_daily_requests_per_user = 3
    yield fake
    fake.httpd.shutdown()


async def choose_free(client: AsyncClient) -> httpx.Response:
    return await client.put(API, json={"preset": "free"})


async def usage_rows() -> list[LLMUsage]:
    async with get_session_factory()() as session:
        return list((await session.execute(select(LLMUsage))).scalars())


async def another_user(client: AsyncClient) -> AsyncClient:
    other = AsyncClient(transport=client._transport, base_url="http://test")
    tokens = await register(other)
    other.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    return other


# --- nothing is sent until the user chooses ------------------------------------------------------


async def test_nothing_goes_to_the_free_model_until_the_user_chooses_it(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    view = (await auth_client.get(API)).json()
    assert view["choice"] is None and view["free_tier"]["chosen"] is False
    assert view["free_tier"].items() >= {"model": MODEL, "host": "127.0.0.1"}.items()
    status = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert status["ready"] is False and status["source"] == "none"
    assert "Choose how to run the AI features" in status["problem"]

    events = await ask(auth_client, await new_conversation(auth_client), QUESTION)
    assert "Choose how to run" in of(events, "error")[0]["message"]
    summary = await auth_client.post(f"/api/v1/documents/{library['lora']}/summary")
    assert summary.status_code == 503
    assert upstream.requests == [] and await usage_rows() == []


async def test_choosing_it_answers_through_the_sites_key(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    saved = await choose_free(auth_client)
    assert saved.status_code == 200, saved.text
    assert SITE_KEY not in saved.text
    body = saved.json()
    assert body["choice"].items() >= {"preset": "free", "model": MODEL, "has_key": False}.items()
    assert body["status"].items() >= {"source": "free", "ready": True, "remote": True}.items()
    assert (body["free_tier"]["used_today"], body["free_tier"]["remaining_today"]) == (0, 3)

    events = await ask(auth_client, await new_conversation(auth_client), QUESTION)
    assert of(events, "answer")[0]["text"] == ANSWER
    [request] = upstream.requests
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == f"Bearer {SITE_KEY}"
    assert request["body"]["model"] == MODEL
    # Nothing that identifies the user goes with the question.
    me = (await auth_client.get("/api/v1/users/me")).json()
    sent = json.dumps(request)
    assert me["id"] not in sent and me["email"] not in sent and "user" not in request["body"]

    [row] = await usage_rows()
    assert (row.provider, row.model, row.status) == ("free", MODEL, "ok")
    assert (await auth_client.get(API)).json()["free_tier"]["remaining_today"] == 2
    # Undoing the choice turns the model off again for this user.
    assert (await auth_client.delete(API)).json()["status"]["ready"] is False


async def test_only_the_person_who_chose_it_uses_it(
    upstream: Upstream, auth_client: AsyncClient, client: AsyncClient
) -> None:
    await choose_free(auth_client)
    other = await another_user(client)
    assert (await auth_client.get("/api/v1/ai/status")).json()["llm"]["ready"] is True
    assert (await other.get("/api/v1/ai/status")).json()["llm"]["ready"] is False


# --- the daily allowance ------------------------------------------------------------------------


async def test_each_user_has_a_daily_allowance(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    await choose_free(auth_client)
    conversation = await new_conversation(auth_client)
    for _ in range(3):
        assert of(await ask(auth_client, conversation, QUESTION + " (again)"), "error") == []
    assert len(upstream.requests) == 3

    refused = of(await ask(auth_client, conversation, "And how many parameters?"), "error")[0]
    assert refused["message"] == "You've used today's 3 free requests."
    assert "UTC" in refused["hint"] and "your own API key" in refused["hint"]
    # A refused call isn't sent and isn't counted: retrying can't use up anyone's share.
    assert len(upstream.requests) == 3 and len(await usage_rows()) == 3
    status = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert status["ready"] is False and "free requests" in status["problem"]
    assert (await auth_client.get(API)).json()["free_tier"]["remaining_today"] == 0


async def test_the_whole_site_can_have_a_daily_limit(
    upstream: Upstream,
    auth_client: AsyncClient,
    client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    settings: Settings,
) -> None:
    settings.free_tier_requests_per_day = 2  # e.g. an OpenRouter key without credits: 50
    await choose_free(auth_client)
    conversation = await new_conversation(auth_client)
    for _ in range(2):
        await ask(auth_client, conversation, QUESTION + " (again)")
    other = await another_user(client)
    await choose_free(other)
    status = (await other.get("/api/v1/ai/status")).json()["llm"]
    assert status["ready"] is False and "shared by everyone" in status["problem"]


async def test_someone_with_their_own_model_is_not_limited(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    server: FakeServer,  # noqa: F811 - fixture
    settings: Settings,
) -> None:
    settings.free_tier_daily_requests_per_user = 0  # the free model is used up for everyone
    server.respond = lambda path, body: ollama_reply(ANSWER)
    saved = await auth_client.put(
        API, json={"preset": "ollama", "model": "mine:7b", "base_url": server.url}
    )
    assert saved.status_code == 200, saved.text
    events = await ask(auth_client, await new_conversation(auth_client), QUESTION)
    assert of(events, "answer")[0]["text"] == ANSWER
    assert upstream.requests == [] and len(server.requests) == 1
    assert SITE_KEY not in json.dumps(server.requests)


async def test_background_jobs_use_and_count_the_allowance(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    settings: Settings,
) -> None:
    settings.free_tier_daily_requests_per_user = 50
    upstream.respond = lambda body: sse("{}")
    await choose_free(auth_client)
    response = await auth_client.post(f"/api/v1/documents/{library['lora']}/summary")
    assert response.status_code in (200, 202), response.text
    await get_dispatcher(settings).drain()
    assert upstream.requests and {r["body"]["model"] for r in upstream.requests} == {MODEL}
    rows = await usage_rows()
    assert len(rows) == len(upstream.requests) and {r.provider for r in rows} == {"free"}
    used = (await auth_client.get(API)).json()["free_tier"]["used_today"]
    assert used == len(rows)


async def test_papers_are_not_summarized_on_upload_with_the_free_model(
    upstream: Upstream, auth_client: AsyncClient, settings: Settings, tmp_path: Any
) -> None:
    from app.demo import sample_papers as sp

    settings.summary_auto = True
    await choose_free(auth_client)
    paper = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    document = await upload(auth_client, settings, "l.pdf", paper)
    await get_dispatcher(settings).drain()
    # Uploading must not spend the allowance or send the paper anywhere.
    assert upstream.requests == []
    summary = (await auth_client.get(f"/api/v1/documents/{document}/summary")).json()
    assert summary is None or summary.get("status") in (None, "none", "missing")


# --- a busy shared model ------------------------------------------------------------------------


async def test_a_busy_answer_is_retried(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    replies = iter([busy(), busy(), sse(ANSWER)])
    upstream.respond = lambda body: next(replies)
    await choose_free(auth_client)
    events = await ask(auth_client, await new_conversation(auth_client), QUESTION)
    assert of(events, "answer")[0]["text"] == ANSWER
    assert len(upstream.requests) == 3 and len(await usage_rows()) == 1


async def test_a_model_that_stays_busy_says_so(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    upstream.respond = lambda body: busy()
    await choose_free(auth_client)
    error = of(await ask(auth_client, await new_conversation(auth_client), QUESTION), "error")[0]
    assert error["message"] == "The free model is busy right now."
    assert "your own API key" in error["hint"]
    assert len(upstream.requests) == 1 + free_tier.RETRIES

    # A wait longer than a call may queue isn't slept through.
    upstream.requests.clear()
    upstream.respond = lambda body: busy(retry_after="86400")
    error = of(await ask(auth_client, await new_conversation(auth_client), QUESTION), "error")[0]
    assert error["message"] == "The free model is busy right now."
    assert len(upstream.requests) == 1


async def test_a_rejected_request_is_not_retried(
    upstream: Upstream,
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
) -> None:
    upstream.respond = lambda body: (401, json.dumps({"error": {"message": "bad key"}}), {})
    await choose_free(auth_client)
    error = of(await ask(auth_client, await new_conversation(auth_client), QUESTION), "error")[0]
    assert "rejected the request" in error["message"] and len(upstream.requests) == 1


async def test_calls_are_paced_for_the_whole_site(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Pacer:
        def __init__(self, answers: list[tuple[bool, int]]) -> None:
            self.answers, self.hits = answers, []

        async def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
            self.hits.append((key, limit, window_seconds))
            return self.answers.pop(0)

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(free_tier.asyncio, "sleep", sleep)
    settings.free_tier_requests_per_minute = 15  # one call every 4 seconds
    pacer = Pacer([(False, 3), (False, 4), (True, 4)])
    monkeypatch.setattr(free_tier, "_pacer", lambda _settings: pacer)
    await free_tier._wait_for_slot(settings, deadline=free_tier.time.monotonic() + 60)
    assert slept == [3, 4] and pacer.hits == [("free-tier", 1, 4)] * 3

    # Too long a queue: give up, without having sent anything.
    monkeypatch.setattr(free_tier, "_pacer", lambda _settings: Pacer([(False, 4)]))
    with pytest.raises(LLMError) as refused:
        await free_tier._wait_for_slot(settings, deadline=free_tier.time.monotonic() + 1)
    assert refused.value.sent is False and "busy" in refused.value.user_message

    # The real in-process pacer: the second call in the same window waits for the next one.
    settings.free_tier_requests_per_minute = 1
    monkeypatch.undo()
    free_tier._local_pacer.reset()
    await free_tier._wait_for_slot(settings, deadline=free_tier.time.monotonic() + 1)
    with pytest.raises(LLMError):
        await free_tier._wait_for_slot(settings, deadline=free_tier.time.monotonic() + 1)
    free_tier._local_pacer.reset()


# --- a server without a free model ---------------------------------------------------------------


async def test_a_server_without_a_free_model_does_not_offer_one(
    auth_client: AsyncClient,
) -> None:
    view = (await auth_client.get(API)).json()
    assert view["free_tier"] is None and view["status"]["ready"] is True  # its default, as before
    refused = await choose_free(auth_client)
    assert refused.status_code == 422 and "no free shared model" in refused.text


async def test_a_free_choice_left_over_falls_back_to_the_servers_model(
    auth_client: AsyncClient,
) -> None:
    me = (await auth_client.get("/api/v1/users/me")).json()
    async with get_session_factory()() as session:  # chosen while the site still had one
        session.add(UserModelChoice(user_id=uuid.UUID(me["id"]), preset="free", model=""))
        await session.commit()
    view = (await auth_client.get(API)).json()
    assert view["choice"] is None
    assert view["status"].items() >= {"source": "server", "ready": True}.items()


# --- the OpenAI-compatible provider --------------------------------------------------------------


async def collect(provider: OpenAICompatibleProvider) -> str:
    events = provider.stream([Message("user", "hi")], GenerationParams())
    return "".join([event.text async for event in events])


async def test_provider_reports_busy_with_the_wait_and_errors_inside_the_stream() -> None:
    def provider(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            MODEL, SITE_KEY, "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler)
        )

    limited = provider(lambda r: httpx.Response(429, headers={"Retry-After": "7"}, json={}))
    with pytest.raises(LLMError) as error:
        await collect(limited)
    assert error.value.busy and (error.value.status, error.value.retry_after) == (429, 7.0)

    # OpenRouter answers 200 and reports an upstream failure as an event in the stream.
    stream = 'data: {"error": {"code": 502, "message": "Provider returned error"}}\n\n'
    inside = provider(lambda r: httpx.Response(200, text=": OPENROUTER PROCESSING\n\n" + stream))
    with pytest.raises(LLMError) as error:
        await collect(inside)
    assert error.value.busy and "Provider returned error" in (error.value.detail or "")

    rejected = provider(lambda r: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(LLMError) as error:
        await collect(rejected)
    assert not error.value.busy


async def test_extra_request_fields_are_sent_but_cannot_replace_the_model() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=sse(ANSWER)[1])

    provider = OpenAICompatibleProvider(
        MODEL,
        SITE_KEY,
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
        extra_body={"reasoning": {"effort": "low", "exclude": True}, "model": "x", "stream": False},
    )
    assert await collect(provider) == ANSWER
    assert seen[0]["reasoning"] == {"effort": "low", "exclude": True}
    assert seen[0]["model"] == MODEL and seen[0]["stream"] is True


# --- the operator's check ------------------------------------------------------------------------


class ScriptedLLM:
    """Answers each call with the next (text, stop reason)."""

    name, model_id, is_remote = "openai", MODEL, True

    def __init__(self, replies: list[tuple[str, str]]) -> None:
        self.replies = replies

    async def stream(self, messages: list[Message], params: GenerationParams) -> Any:
        from app.services.llm.base import StreamEvent, Usage

        text, stop = self.replies.pop(0)
        yield StreamEvent(text=text)
        yield StreamEvent(done=True, usage=Usage(100, 50), stop_reason=stop, model=MODEL)


GOOD_ANSWER = "Low-rank adapters cut GPU memory by 60 percent [1]."
GOOD_SUMMARY = (
    "PROBLEM: Fine-tuning every parameter is expensive [1].\n"
    "CONTRIBUTION: Low-rank adapters train 0.4 percent of the parameters [1].\n"
    "LIMITATIONS: Only models up to seven billion parameters were tested [3]."
)
# What Nemotron 3 Ultra sent back with its reasoning left on (2026-10-11): the thinking, in the
# answer, cut off at the budget before any field was written.
THINKING = (
    "The user wants me to summarize the paper using only the provided passages. I need to "
    "answer three fields: PROBLEM, CONTRIBUTION, LIMITATIONS.\n\nNow, PROBLEM: What problem "
    "does the paper address? The problem is that fine-tuning is expensive. This is in [1]"
)


@pytest.mark.parametrize(
    ("replies", "code", "said"),
    [
        ([(GOOD_ANSWER, "stop"), (GOOD_SUMMARY, "stop")], 0, "Both came back right."),
        ([(GOOD_ANSWER, "stop"), (THINKING, "length")], 1, "cut off at the answer budget"),
        ([(GOOD_ANSWER, "stop"), (THINKING, "stop")], 1, "before the first field"),
        ([(GOOD_ANSWER, "stop"), ("PROBLEM: It is expensive [1].", "stop")], 1, "not filled in"),
        ([("", "length"), (GOOD_SUMMARY, "stop")], 1, "the reply was empty"),
    ],
)
async def test_check_model_says_whether_answers_and_summaries_come_back_right(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    replies: list[tuple[str, str]],
    code: int,
    said: str,
) -> None:
    from app import cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "server_provider", lambda _settings: ScriptedLLM(list(replies)))
    assert await cli.check_model() == code
    printed = capsys.readouterr().out
    assert said in printed
    assert ("LLM_EXTRA_BODY" in printed) == bool(code)  # how to fix it, only when it's needed

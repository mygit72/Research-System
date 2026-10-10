"""Each user's own model: their API key (encrypted, never shown again) or a local model.

Hosted providers are never called: their requests are checked against httpx mock transports,
and "local" models are a stand-in Ollama / OpenAI-compatible server on 127.0.0.1.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Environment, Settings
from app.core.database import get_session_factory
from app.models.audit import AuditLog
from app.models.model_choice import UserModelChoice
from app.models.usage import LLMUsage
from app.services.llm import get_llm, resolve_model
from app.services.llm import user_models as um
from app.services.llm.user_models import KeyUnreadable, decrypt_key, encrypt_key
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_chat_api import ask, library, new_conversation, of  # noqa: F401 - fixture
from tests.test_project_code import make_project
from tests.test_starter_generation import FakeServer, ollama_reply, server  # noqa: F401 - fixture

API = "/api/v1/users/me/model"
GROQ_KEY = "gsk_test_0123456789abcdefWXYZ"


async def choose(client: AsyncClient, **body: Any) -> httpx.Response:
    return await client.put(API, json=body)


async def choice_row(user_email_client: AsyncClient) -> UserModelChoice | None:
    me = (await user_email_client.get("/api/v1/users/me")).json()
    async with get_session_factory()() as session:
        return (
            await session.execute(
                select(UserModelChoice).where(UserModelChoice.user_id == uuid.UUID(me["id"]))
            )
        ).scalar_one_or_none()


# --- keys at rest -------------------------------------------------------------------------------


def test_keys_are_encrypted_and_tied_to_the_servers_secret(settings: Settings) -> None:
    token = encrypt_key(settings, GROQ_KEY)
    assert GROQ_KEY not in token and token != encrypt_key(settings, GROQ_KEY)  # random IV
    assert decrypt_key(settings, token) == GROQ_KEY
    rotated = settings.model_copy(update={"jwt_secret": SecretStr("another-secret-" * 4)})
    with pytest.raises(KeyUnreadable):
        decrypt_key(rotated, token)
    dedicated = settings.model_copy(update={"model_key_secret": SecretStr("model-key-secret-" * 3)})
    assert decrypt_key(dedicated, encrypt_key(dedicated, GROQ_KEY)) == GROQ_KEY
    with pytest.raises(KeyUnreadable):  # MODEL_KEY_SECRET, once set, is what counts
        decrypt_key(dedicated, token)


# --- choosing ---------------------------------------------------------------------------------


async def test_by_default_the_server_model_is_used(auth_client: AsyncClient) -> None:
    body = (await auth_client.get(API)).json()
    assert body["choice"] is None
    assert body["status"]["source"] == "server" and body["status"]["ready"] is True
    presets = {p["id"]: p for p in body["options"]["presets"]}
    assert set(presets) == set(um.PRESETS)
    assert presets["groq"]["base_url"] == "https://api.groq.com/openai/v1"
    assert presets["ollama"]["local"] and presets["ollama"]["available"]  # not production


async def test_a_saved_key_is_never_shown_logged_or_exported_again(
    auth_client: AsyncClient,
) -> None:
    response = await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert GROQ_KEY not in response.text
    assert {**body["choice"], "updated_at": None} == {
        "preset": "groq",
        "label": "Groq",
        "model": "llama-3.3-70b",
        "base_url": "https://api.groq.com/openai/v1",
        "has_key": True,
        "key_hint": "…WXYZ",
        "updated_at": None,
    }
    assert body["status"].items() >= {"source": "user", "provider": "groq", "ready": True}.items()
    assert GROQ_KEY not in (await auth_client.get(API)).text

    row = await choice_row(auth_client)
    assert row is not None and row.api_key_encrypted and GROQ_KEY not in row.api_key_encrypted
    async with get_session_factory()() as session:
        audits = list((await session.execute(select(AuditLog))).scalars())
    changed = [a for a in audits if a.action == "user.model_changed"]
    assert changed and changed[0].details == {"preset": "groq", "model": "llama-3.3-70b"}

    export = await auth_client.get("/api/v1/users/me/export")
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    everything = b"".join(archive.read(name) for name in archive.namelist())
    assert GROQ_KEY.encode() not in everything
    assert row.api_key_encrypted.encode() not in everything  # not even the ciphertext
    account = json.loads(archive.read("account.json"))
    assert account["model_choice"][0]["preset"] == "groq"


async def test_changing_the_model_keeps_the_key_and_reset_forgets_it(
    auth_client: AsyncClient,
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    kept = await choose(auth_client, preset="groq", model="qwen-qwq-32b")  # no key: keep it
    assert kept.status_code == 200 and kept.json()["choice"]["key_hint"] == "…WXYZ"
    other = await choose(auth_client, preset="gemini", model="gemini-flash")  # another provider
    assert other.status_code == 422 and "Gemini API key" in other.json()["error"]["message"]
    reset = await auth_client.delete(API)
    assert reset.json()["choice"] is None and reset.json()["status"]["source"] == "server"
    assert await choice_row(auth_client) is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"preset": "nope", "model": "x"}, "Unknown provider"),
        ({"preset": "groq", "model": "", "api_key": GROQ_KEY}, "Choose a model"),
        ({"preset": "groq", "model": "a b", "api_key": GROQ_KEY}, "Choose a model"),
        ({"preset": "groq", "model": "m", "api_key": "has space key"}, "doesn't look like"),
        ({"preset": "ollama", "model": "m", "base_url": "ftp://x"}, "http:// or https://"),
        ({"preset": "custom", "model": "m", "base_url": "http://u:p@h:1/v1"}, "key field"),
    ],
)
async def test_bad_choices_are_refused_with_a_reason(
    auth_client: AsyncClient, body: dict[str, Any], message: str
) -> None:
    response = await choose(auth_client, **body)
    assert response.status_code == 422 and message in response.json()["error"]["message"]


async def test_a_public_server_offers_keys_but_not_local_models(
    auth_client: AsyncClient, settings: Settings
) -> None:
    settings.environment = Environment.PRODUCTION  # allow_local_models unset: production says no
    options = {p["id"]: p for p in (await auth_client.get(API)).json()["options"]["presets"]}
    assert not options["ollama"]["available"] and not options["custom"]["available"]
    assert options["groq"]["available"]
    refused = await choose(auth_client, preset="ollama", model="llama3.2", base_url="http://x:1")
    assert refused.status_code == 422 and "can't reach local models" in refused.text
    test = await auth_client.post(
        f"{API}/test", json={"preset": "custom", "base_url": "http://10.0.0.1"}
    )
    assert test.status_code == 422  # the server never probes its own network for a user
    settings.allow_local_models = True  # a self-hosted install says so explicitly
    allowed = await choose(auth_client, preset="ollama", model="llama3.2", base_url="http://x:1")
    assert allowed.status_code == 200


async def test_local_only_servers_refuse_keys_even_ones_saved_before(
    auth_client: AsyncClient, settings: Settings
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    settings.local_only = True
    status = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert status["ready"] is False and "LOCAL_ONLY" in status["problem"]
    again = await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    assert again.status_code == 422


async def test_a_key_saved_under_an_old_secret_asks_to_be_entered_again(
    auth_client: AsyncClient, settings: Settings
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    email = await choice_email(auth_client)
    settings.jwt_secret = SecretStr("a-new-jwt-secret-after-rotation-0123456789")
    # the session token was signed with the old secret too: sign in again
    login = await auth_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-42"}
    )
    assert login.status_code == 200, login.text
    auth_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    status = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    assert status["ready"] is False and "can't be read" in status["problem"]
    retest = await auth_client.post(f"{API}/test", json={"preset": "groq"})
    assert retest.status_code == 422 and "enter it again" in retest.text


async def choice_email(client: AsyncClient) -> str:
    return str((await client.get("/api/v1/users/me")).json()["email"])


async def test_each_user_gets_their_own_model(
    auth_client: AsyncClient, client: AsyncClient
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    mine = (await auth_client.get("/api/v1/ai/status")).json()["llm"]
    other = AsyncClient(transport=client._transport, base_url="http://test")
    tokens = await register(other)
    other.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    theirs = (await other.get("/api/v1/ai/status")).json()["llm"]
    assert mine["source"] == "user" and theirs["source"] == "server"
    assert (await auth_client.get("/api/v1/ai/status")).json()["llm"]["source"] == "user"


# --- testing a connection -----------------------------------------------------------------------


async def test_listing_models_goes_to_the_presets_fixed_address(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})

    result = await um.list_models(
        settings, "groq", um.PRESETS["groq"].base_url, GROQ_KEY, httpx.MockTransport(handler)
    )
    assert result.ok and result.models == ["a-model", "b-model"]
    assert str(seen[0].url) == "https://api.groq.com/openai/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {GROQ_KEY}"

    rejected = await um.list_models(
        settings,
        "gemini",
        um.PRESETS["gemini"].base_url,
        "bad-key-123",
        httpx.MockTransport(lambda r: httpx.Response(401, json={})),
    )
    assert not rejected.ok and rejected.message == "Google Gemini rejected the key."
    redirect = await um.list_models(
        settings,
        "openrouter",
        um.PRESETS["openrouter"].base_url,
        "k-123456789",
        httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://10.0.0.1"})),
    )
    assert not redirect.ok  # redirects are never followed


def ollama_tags(*names: str) -> Any:
    return lambda path: (200, {"models": [{"name": n} for n in names]})


async def test_the_connection_test_lists_a_local_servers_models(
    auth_client: AsyncClient,
    server: FakeServer,  # noqa: F811 - fixture
) -> None:
    server.respond_get = ollama_tags("qwen2.5:3b", "llama3.2:3b")
    response = await auth_client.post(
        f"{API}/test", json={"preset": "ollama", "base_url": server.url}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "models": ["llama3.2:3b", "qwen2.5:3b"],
        "message": "Connected: 2 model(s) available.",
    }
    down = await auth_client.post(
        f"{API}/test", json={"preset": "ollama", "base_url": "http://127.0.0.1:9"}
    )
    assert down.json()["ok"] is False and "Is Ollama running?" in down.json()["message"]


# --- the user's model does the work --------------------------------------------------------------


async def test_chat_answers_with_the_users_local_model(
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    server: FakeServer,  # noqa: F811 - fixture
) -> None:
    server.respond = lambda path, body: ollama_reply("Low-rank adapters cut GPU memory [1].")
    saved = await choose(auth_client, preset="ollama", model="my-model:7b", base_url=server.url)
    assert saved.status_code == 200, saved.text
    conversation = await new_conversation(auth_client)
    events = await ask(auth_client, conversation, "How much GPU memory do low-rank adapters save?")
    assert of(events, "answer")[0]["text"] == "Low-rank adapters cut GPU memory [1]."
    [request] = server.requests
    assert request["path"] == "/api/chat" and request["body"]["model"] == "my-model:7b"
    detail = (await auth_client.get(f"/api/v1/chat/conversations/{conversation}")).json()
    config = detail["messages"][-1]["generation_config"]
    assert (config["llm_provider"], config["llm_model"]) == ("ollama", "my-model:7b")
    async with get_session_factory()() as session:
        usage = list((await session.execute(select(LLMUsage))).scalars())
    assert [(u.provider, u.model) for u in usage] == [("ollama", "my-model:7b")]


async def test_the_servers_own_key_never_goes_to_a_users_address(
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    server: FakeServer,  # noqa: F811 - fixture
    settings: Settings,
) -> None:
    settings.openai_api_key = SecretStr("sk-server-own-secret-key")
    server.respond = lambda path, body: (200, {})
    await choose(auth_client, preset="custom", model="any", base_url=server.url + "/v1")
    conversation = await new_conversation(auth_client)
    await ask(auth_client, conversation, "How much GPU memory do low-rank adapters save?")
    [request] = server.requests
    assert request["path"] == "/v1/chat/completions"
    sent = json.dumps(request["headers"]) + json.dumps(request["body"])
    assert "sk-server-own-secret-key" not in sent and "authorization" not in sent.lower()


async def test_background_jobs_run_on_the_owners_model(
    auth_client: AsyncClient,
    library: dict[str, str],  # noqa: F811 - fixture
    server: FakeServer,  # noqa: F811 - fixture
    settings: Settings,
) -> None:
    server.respond_get = ollama_tags("owner-model")
    server.respond = lambda path, body: ollama_reply("{}")
    await choose(auth_client, preset="ollama", model="owner-model", base_url=server.url)
    response = await auth_client.post(f"/api/v1/documents/{library['lora']}/summary")
    assert response.status_code in (200, 202), response.text
    await get_dispatcher(settings).drain()
    assert server.requests and {r["body"]["model"] for r in server.requests} == {"owner-model"}


async def test_outside_a_request_the_server_model_is_used(settings: Settings) -> None:
    assert um.active_model() is None
    assert resolve_model(settings) == get_llm(settings).model_id


async def test_the_starter_code_uses_the_users_model_but_never_their_key(
    auth_client: AsyncClient,
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    pid = await make_project(auth_client, ["toy"], builds_on=("RAG",))
    files = (await auth_client.get(f"/api/v1/projects/{pid}/code")).json()["files"]
    by_path = {f["path"]: f["content"] for f in files}
    generator = json.loads(by_path["config.json"])["generator"]
    assert (
        generator.items()
        >= {
            "provider": "openai",
            "model": "llama-3.3-70b",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key_env": "GROQ_API_KEY",
        }.items()
    )
    assert all(GROQ_KEY not in content for content in by_path.values())
    assert "setx GROQ_API_KEY" in by_path["README.md"]


async def test_deleting_the_account_deletes_the_saved_key(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    await choose(auth_client, preset="groq", model="llama-3.3-70b", api_key=GROQ_KEY)
    assert (await auth_client.delete("/api/v1/users/me")).status_code == 204
    async with get_session_factory()() as session:
        assert list((await session.execute(select(UserModelChoice))).scalars()) == []

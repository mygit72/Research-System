"""Research Watches: CRUD, running (manual and the regression test for run_after_commit),
auto-import, the review queue, and LOCAL_ONLY / no-LLM graceful degradation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services import webhooks
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"


def _feed(arxiv_id: str = "2501.00001", title: str = "Low Rank Adapters at Scale") -> str:
    published = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/{arxiv_id}v1</id>
    <published>{published}</published>
    <title>{title}</title>
    <summary>A study of low rank adapters for efficient fine-tuning at scale.</summary>
  </entry>
</feed>"""


def _multi_feed() -> str:
    published = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    entries = "\n".join(
        f"""<entry>
    <id>http://arxiv.org/abs/2501.0000{i}v1</id>
    <published>{published}</published>
    <title>Low Rank Adapters, Part {i}</title>
    <summary>A study of low rank adapters for efficient fine-tuning at scale, part {i}.</summary>
  </entry>"""
        for i in range(1, 4)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
{entries}
</feed>"""


@pytest.fixture
def pdf(tmp_path: Path) -> bytes:
    return sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()


@pytest.fixture
def serve_multi(monkeypatch: pytest.MonkeyPatch, pdf: bytes) -> list[str]:
    """Like `serve`, but the arXiv search returns 3 distinct candidates (for synthesis tests)."""
    from app.services import arxiv

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text=_multi_feed())
        return httpx.Response(200, content=pdf)

    monkeypatch.setattr(
        arxiv, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch, pdf: bytes) -> list[str]:
    """Canned arXiv search + fetch; returns the list of requested URLs."""
    from app.services import arxiv

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text=_feed())
        return httpx.Response(200, content=pdf)

    monkeypatch.setattr(
        arxiv, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


async def make_watch(client: AsyncClient, **overrides: object) -> dict[str, object]:
    body = {"name": "Mine", "query": "low rank adapters", "relevance_threshold": 0.0}
    body.update(overrides)
    response = await client.post(f"{API}/watches", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_applies_defaults(auth_client: AsyncClient) -> None:
    watch = await make_watch(auth_client, relevance_threshold=None)
    assert watch["interval_hours"] == 24
    assert watch["relevance_threshold"] == 0.35
    assert watch["auto_import"] is False
    assert watch["status"] == "active"
    assert watch["latest_run"] is None


async def test_interval_floor_is_enforced(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"{API}/watches", json={"name": "Mine", "query": "x", "interval_hours": 1}
    )
    assert response.status_code == 422


async def test_active_watch_cap_is_enforced(auth_client: AsyncClient, settings: Settings) -> None:
    for _ in range(settings.agent_watch_max_active_per_user):
        await make_watch(auth_client)
    response = await auth_client.post(
        f"{API}/watches", json={"name": "One more", "query": "x"}
    )
    assert response.status_code == 409


async def test_create_validates_collection_ownership(auth_client: AsyncClient) -> None:
    import uuid

    response = await auth_client.post(
        f"{API}/watches",
        json={"name": "Mine", "query": "x", "collection_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


async def test_list_get_update_delete(auth_client: AsyncClient) -> None:
    watch = await make_watch(auth_client)
    assert (await auth_client.get(f"{API}/watches")).json()[0]["id"] == watch["id"]
    assert (await auth_client.get(f"{API}/watches/{watch['id']}")).json()["id"] == watch["id"]

    paused = await auth_client.patch(f"{API}/watches/{watch['id']}", json={"status": "paused"})
    assert paused.json()["status"] == "paused"

    deleted = await auth_client.delete(f"{API}/watches/{watch['id']}")
    assert deleted.status_code == 204
    assert (await auth_client.get(f"{API}/watches/{watch['id']}")).status_code == 404
    assert (await auth_client.get(f"{API}/watches/{watch['id']}/runs")).status_code == 404


async def test_run_now_produces_a_scored_digest_and_a_notification(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    watch = await make_watch(auth_client, relevance_threshold=0.0)
    run = await auth_client.post(f"{API}/watches/{watch['id']}/run")
    assert run.status_code == 202
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    assert detail["latest_run"]["candidates_above_threshold"] >= 1

    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()
    assert digest["items"]
    entry = digest["items"][0]
    assert entry["score"] > 0
    assert entry["import_status"] == "pending"
    trace = entry["trace"]
    assert trace["search_query"] == watch["query"]
    assert trace["relevance_threshold"] == 0.0
    assert trace["rank"] >= 1
    assert trace["candidates_in_run"] >= len(digest["items"])
    assert trace["anchor_project_question"] is None

    notifications = (await auth_client.get(f"{API}/notifications")).json()
    assert notifications["items"], "a kept candidate must produce a notification"


async def test_run_now_posts_to_a_saved_webhook(
    auth_client: AsyncClient, settings: Settings, serve: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append((str(request.url), request.content))
        return httpx.Response(200)

    monkeypatch.setattr(
        webhooks,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    slack_url = "https://hooks.slack.com/services/T000/B000/xxxxxxxxxxxxxxxxxxxx"
    await auth_client.put(f"{API}/users/me/webhooks/slack", json={"url": slack_url})

    watch = await make_watch(auth_client, relevance_threshold=0.0)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    assert len(posted) == 1
    url, body = posted[0]
    assert url == slack_url
    assert watch["name"].encode() in body


async def test_run_now_stays_quiet_when_nothing_clears_the_threshold(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    watch = await make_watch(auth_client, relevance_threshold=1.0)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    assert detail["latest_run"]["candidates_above_threshold"] == 0
    assert (await auth_client.get(f"{API}/notifications")).json()["items"] == []


async def test_run_now_refuses_while_a_run_is_in_flight(
    auth_client: AsyncClient, serve: list[str]
) -> None:
    watch = await make_watch(auth_client)
    first = await auth_client.post(f"{API}/watches/{watch['id']}/run")
    assert first.status_code == 202
    second = await auth_client.post(f"{API}/watches/{watch['id']}/run")
    assert second.status_code == 409


async def test_auto_import_attaches_to_collection_and_the_document_leaves_queued(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    """Regression test: without `run_after_commit` in the runner, this document.process job
    would be registered but never dispatched, and the imported document would stay QUEUED."""
    collection = (
        await auth_client.post(f"{API}/collections", json={"name": "Adapters"})
    ).json()
    watch = await make_watch(
        auth_client,
        relevance_threshold=0.0,
        auto_import=True,
        collection_id=collection["id"],
    )
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    # One drain() transitively runs the watch AND the document.process job it enqueues: the
    # dispatcher's drain loop keeps gathering as long as any task is still registered, so a
    # cascaded job started from inside a running job is swept up in the same call. If the
    # `run_after_commit` call in the runner were missing, document.process would never be
    # dispatched at all and the document would stay "queued" forever, no matter how many
    # times this is drained.
    await get_dispatcher(settings).drain()

    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"]
    assert digest[0]["import_status"] == "imported"
    document_id = digest[0]["document_id"]
    assert document_id is not None

    document = (await auth_client.get(f"{API}/documents/{document_id}")).json()
    assert document["status"] == "ready"

    collection_detail = (await auth_client.get(f"{API}/collections/{collection['id']}")).json()
    assert any(d["id"] == document_id for d in collection_detail["documents"])


async def test_auto_import_already_in_library_is_not_a_failure(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    imported = await auth_client.post(
        f"{API}/documents/import", json={"refs": ["2501.00001"]}
    )
    assert imported.status_code == 201, imported.text
    await get_dispatcher(settings).drain()
    calls_before = len(serve)

    watch = await make_watch(auth_client, relevance_threshold=0.0, auto_import=True)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"]
    assert digest[0]["import_status"] == "already_in_library"
    assert digest[0]["document_id"] == imported.json()["items"][0]["id"]
    # No second PDF download: only the search call was made this time.
    assert len(serve) == calls_before + 1


async def test_manual_import_from_digest(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    watch = await make_watch(auth_client, relevance_threshold=0.0)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()
    entry = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"][0]

    imported = await auth_client.post(
        f"{API}/watches/{watch['id']}/digest/{entry['id']}/import"
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["import_status"] == "imported"

    again = await auth_client.post(f"{API}/watches/{watch['id']}/digest/{entry['id']}/import")
    assert again.status_code == 409


async def test_local_only_run_skips_cleanly_and_advances_the_schedule(
    auth_client: AsyncClient,
    settings: Settings,
    serve: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "local_only", True)
    watch = await make_watch(auth_client)
    before = watch["next_run_at"]
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    assert "Skipped" in (detail["latest_run"]["error_message"] or "")
    assert detail["next_run_at"] != before
    assert serve == []


async def test_blurb_is_null_when_no_model_is_ready(
    auth_client: AsyncClient,
    settings: Settings,
    serve: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    watch = await make_watch(auth_client, relevance_threshold=0.0)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    entry = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"][0]
    assert entry["blurb"] is None


async def test_synthesize_imports_despite_auto_import_off_and_writes_a_review(
    auth_client: AsyncClient, settings: Settings, serve_multi: list[str]
) -> None:
    watch = await make_watch(
        auth_client, relevance_threshold=0.0, auto_import=False, synthesize=True
    )
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    # One drain() transitively runs the watch job, the three document.process jobs it starts
    # for synthesis (despite auto_import=False), the wait loop in between, and the
    # report.generate job it kicks off once they're ready — see the drain() comment on the
    # auto-import regression test above for why one call is enough.
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    report_id = detail["latest_run"]["report_id"]
    assert report_id is not None

    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"]
    assert len(digest) == 3
    assert all(e["import_status"] == "imported" for e in digest)  # imported for synthesis

    report = await auth_client.get(f"{API}/reports/{report_id}")
    assert report.status_code == 200, report.text
    assert report.json()["kind"] == "review"


async def test_synthesize_is_skipped_quietly_with_no_model_configured(
    auth_client: AsyncClient,
    settings: Settings,
    serve_multi: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    watch = await make_watch(
        auth_client, relevance_threshold=0.0, auto_import=False, synthesize=True
    )
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["status"] == "succeeded"
    assert detail["latest_run"]["report_id"] is None
    # The papers were still imported (synthesis needs to read them to try), even though no
    # review could be written.
    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"]
    assert all(e["import_status"] == "imported" for e in digest)


async def test_fewer_than_three_kept_never_triggers_synthesis(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    watch = await make_watch(
        auth_client, relevance_threshold=0.0, auto_import=False, synthesize=True
    )
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    detail = (await auth_client.get(f"{API}/watches/{watch['id']}")).json()
    assert detail["latest_run"]["report_id"] is None
    digest = (await auth_client.get(f"{API}/watches/{watch['id']}/digest")).json()["items"]
    assert digest[0]["import_status"] == "pending"  # never imported: auto_import is off too

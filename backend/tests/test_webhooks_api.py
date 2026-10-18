"""Settings -> Notifications: save/list/delete a webhook, host validation, /test posting."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from app.services import webhooks

API = "/api/v1"
SLACK_URL = "https://hooks.slack.com/services/T000/B000/xxxxxxxxxxxxxxxxxxxx"


async def test_save_list_and_delete(auth_client: AsyncClient) -> None:
    saved = await auth_client.put(f"{API}/users/me/webhooks/slack", json={"url": SLACK_URL})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["platform"] == "slack"
    assert body["url_hint"] == "…xxxxxx"
    assert SLACK_URL not in str(body)  # the full URL is never echoed back

    listed = (await auth_client.get(f"{API}/users/me/webhooks")).json()
    assert [c["platform"] for c in listed] == ["slack"]

    deleted = await auth_client.delete(f"{API}/users/me/webhooks/slack")
    assert deleted.status_code == 200
    assert (await auth_client.get(f"{API}/users/me/webhooks")).json() == []


async def test_saving_replaces_the_existing_url_for_that_platform(auth_client: AsyncClient) -> None:
    await auth_client.put(f"{API}/users/me/webhooks/slack", json={"url": SLACK_URL})
    other = SLACK_URL.replace("xxxxxxxxxxxxxxxxxxxx", "yyyyyyyyyyyyyyyyyyyy")
    await auth_client.put(f"{API}/users/me/webhooks/slack", json={"url": other})
    listed = (await auth_client.get(f"{API}/users/me/webhooks")).json()
    assert len(listed) == 1 and listed[0]["url_hint"] == "…yyyyyy"


async def test_a_url_on_an_unknown_host_is_refused(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        f"{API}/users/me/webhooks/slack", json={"url": "https://evil.example/x"}
    )
    assert response.status_code == 422
    assert (await auth_client.get(f"{API}/users/me/webhooks")).json() == []


async def test_deleting_a_platform_with_nothing_saved_404s(auth_client: AsyncClient) -> None:
    response = await auth_client.delete(f"{API}/users/me/webhooks/discord")
    assert response.status_code == 404


async def test_test_endpoint_posts_and_reports_failure(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    monkeypatch.setattr(
        webhooks,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await auth_client.put(f"{API}/users/me/webhooks/slack", json={"url": SLACK_URL})
    ok = await auth_client.post(f"{API}/users/me/webhooks/slack/test")
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}
    assert seen == [SLACK_URL]

    monkeypatch.setattr(
        webhooks,
        "client_factory",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ),
    )
    failed = await auth_client.post(f"{API}/users/me/webhooks/slack/test")
    assert failed.json() == {"ok": False}


async def test_test_endpoint_404s_with_nothing_saved(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"{API}/users/me/webhooks/discord/test")
    assert response.status_code == 404

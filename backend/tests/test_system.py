from __future__ import annotations

from httpx import AsyncClient

from app.core.config import Settings
from app.core.errors import AppError


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    )


async def test_docs_page_can_load_its_scripts(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200 and "content-security-policy" not in response.headers


async def test_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


async def test_ready_reports_components(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    components = {c["name"]: c["status"] for c in response.json()["components"]}
    assert components == {"database": "ok", "redis": "disabled"}


async def test_public_config_has_no_secrets(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/config")).json()
    assert body["app_name"]
    assert "jwt" not in str(body).lower()
    assert "secret" not in str(body).lower()


async def test_prometheus_metrics(client: AsyncClient) -> None:
    await client.get("/health")
    text = (await client.get("/metrics")).text
    assert 'http_requests_total{method="GET",path="/health",status="200"}' in text
    assert "http_request_duration_ms_bucket" in text


async def test_metrics_token_is_required_when_configured(
    client: AsyncClient, settings: Settings
) -> None:
    from pydantic import SecretStr

    settings.metrics_token = SecretStr("s3cret-scrape")
    assert (await client.get("/metrics")).status_code == 401
    wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = await client.get("/metrics", headers={"Authorization": "Bearer s3cret-scrape"})
    assert right.status_code == 200 and "http_requests_total" in right.text


async def test_errors_have_consistent_shape(client: AsyncClient, app: object) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]

    @app.get("/boom")  # type: ignore[attr-defined]
    async def boom() -> None:
        raise AppError("Friendly message", hint="Do this instead")

    boom_response = await client.get("/boom")
    assert boom_response.json()["error"]["message"] == "Friendly message"
    assert boom_response.json()["error"]["hint"] == "Do this instead"


async def test_auth_rate_limit(client: AsyncClient, settings: Settings) -> None:
    settings.rate_limit_enabled = True
    settings.auth_rate_limit_per_minute = 3
    statuses = []
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "whatever-123"}
        )
        statuses.append(response.status_code)
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]
    assert response.headers["retry-after"]


def test_production_rejects_default_secret() -> None:
    import pytest

    from app.core.config import Environment

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(environment=Environment.PRODUCTION).validate_for_production()


async def test_session_refresh_is_not_limited_like_logins(
    client: AsyncClient, settings: Settings
) -> None:
    """Reloading the app refreshes the session; that must not count as a login attempt."""
    from tests.conftest import register

    await register(client)  # sets the refresh cookie
    settings.rate_limit_enabled = True
    settings.auth_rate_limit_per_minute = 3
    for _ in range(6):  # six page loads in a row
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 200, response.text
    for _ in range(3):
        await client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-1234"}
        )
    blocked = await client.post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-1234"}
    )
    assert blocked.status_code == 429  # credential guessing is still limited
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200

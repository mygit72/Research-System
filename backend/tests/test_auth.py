from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import register


async def test_register_returns_tokens_and_user(client: AsyncClient) -> None:
    body = await register(client, "Ada@Example.com")
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "ada@example.com"  # normalized
    assert "password" not in str(body["user"])


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    await register(client, "dup@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "DUP@example.com", "password": "another-pass-9"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert response.json()["error"]["hint"]


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "at least" in error["message"]


async def test_login_success_and_failure(client: AsyncClient) -> None:
    await register(client, "login@example.com")
    ok = await client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "correct-horse-42"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "wrong-password-1"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    # Same message either way: don't reveal which emails are registered.
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users/me")).status_code == 401
    bad = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_refresh_rotates_and_detects_reuse(client: AsyncClient) -> None:
    tokens = await register(client)
    first = tokens["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    # Replaying the old token is treated as theft: it fails AND kills the new one.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    tokens = await register(client)
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 204
    again = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert again.status_code == 401


async def test_change_password(auth_client: AsyncClient) -> None:
    me = (await auth_client.get("/api/v1/users/me")).json()
    wrong = await auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "nope-nope-1", "new_password": "brand-new-pass-7"},
    )
    assert wrong.status_code == 422
    ok = await auth_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "correct-horse-42", "new_password": "brand-new-pass-7"},
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    login = await auth_client.post(
        "/api/v1/auth/login", json={"email": me["email"], "password": "brand-new-pass-7"}
    )
    assert login.status_code == 200


async def test_refresh_via_httponly_cookie(client: AsyncClient) -> None:
    """Browser flow: the refresh token travels only in an httpOnly cookie."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "cookie@example.com", "password": "correct-horse-42"},
    )
    set_cookie = response.headers["set-cookie"].lower()
    assert "ri_refresh=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/v1/auth" in set_cookie

    # httpx stores the cookie; no body needed.
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

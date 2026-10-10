from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import register


async def test_get_and_update_profile(auth_client: AsyncClient) -> None:
    me = await auth_client.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["full_name"] == "Ada Researcher"

    updated = await auth_client.patch(
        "/api/v1/users/me",
        json={"full_name": "Ada L.", "preferences": {"theme": "dark"}},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Ada L."

    # Preferences merge rather than replace.
    merged = await auth_client.patch(
        "/api/v1/users/me", json={"preferences": {"sidebar_collapsed": True}}
    )
    assert merged.json()["preferences"] == {"theme": "dark", "sidebar_collapsed": True}


async def test_unknown_preference_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.patch(
        "/api/v1/users/me", json={"preferences": {"not_a_setting": 1}}
    )
    assert response.status_code == 422


async def test_sessions_list_and_revoke(client: AsyncClient) -> None:
    tokens = await register(client, "sessions@example.com")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "sessions@example.com", "password": "correct-horse-42"},
    )
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    sessions = (await client.get("/api/v1/users/me/sessions", headers=headers)).json()
    assert len(sessions) == 2

    revoked = await client.delete(f"/api/v1/users/me/sessions/{sessions[0]['id']}", headers=headers)
    assert revoked.status_code == 204
    remaining = (await client.get("/api/v1/users/me/sessions", headers=headers)).json()
    assert len(remaining) == 1


async def test_delete_account(client: AsyncClient) -> None:
    tokens = await register(client, "bye@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.delete("/api/v1/users/me", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": "bye@example.com", "password": "correct-horse-42"}
    )
    assert login.status_code == 401


async def test_users_are_isolated(client: AsyncClient) -> None:
    a = await register(client)
    b = await register(client)
    me_a = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {a['access_token']}"}
    )
    me_b = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {b['access_token']}"}
    )
    assert me_a.json()["id"] != me_b.json()["id"]

"""Personal data: full export, security activity, and account deletion that leaves nothing behind."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import get_session_factory
from app.demo import sample_papers as sp
from app.models.document import DocumentVersion
from app.services.storage import get_storage
from app.services.vectorstore import VectorFilter, collection_name, get_vector_store
from tests.conftest import register
from tests.test_indexing_api import upload

API = "/api/v1"


async def test_export_has_everything_mine_and_no_secrets(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    pdf = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "lora.pdf").read_bytes()
    doc = await upload(auth_client, settings, "lora.pdf", pdf)
    await auth_client.post(f"{API}/notes", json={"content": "Check table 2", "document_id": doc})
    owner = auth_client.headers["Authorization"]
    other = await register(client)  # someone else's data must not appear
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    await client.post(f"{API}/notes", json={"content": "Not yours"})
    client.headers["Authorization"] = owner

    response = await auth_client.get(f"{API}/users/me/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert {"README.txt", "account.json", "library.json", "chat.json", "usage.json"} <= names

    account = json.loads(archive.read("account.json"))
    assert "password_hash" not in account and account["email"]
    library = json.loads(archive.read("library.json"))
    assert [p["id"] for p in library["papers"]] == [doc]
    assert [n["content"] for n in library["notes"]] == ["Check table 2"]
    [original] = [n for n in names if n.startswith("files/")]
    assert original.endswith("lora.pdf") and archive.read(original) == pdf
    assert "token_hash" not in archive.read("activity.json").decode()

    activity = (await auth_client.get(f"{API}/users/me/activity")).json()
    actions = [a["action"] for a in activity]
    assert actions[0] == "user.exported" and "user.register" in actions


async def test_deleting_the_account_removes_files_and_index_entries(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    pdf = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "lora.pdf").read_bytes()
    doc = await upload(auth_client, settings, "lora.pdf", pdf)
    async with get_session_factory()() as session:
        version = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc))
            )
        ).scalar_one()
    storage = get_storage(settings)
    original, derived = storage.path(version.storage_key), storage.derived_dir(version.id)
    assert original.exists() and derived.exists()
    store = get_vector_store(settings)
    name = collection_name("chunks", version.embedding_model, version.embedding_dimension)  # type: ignore[arg-type]
    mine = VectorFilter(user_id=version.user_id, document_ids=[uuid.UUID(doc)])
    assert store.count(name, mine) > 0

    response = await auth_client.delete(f"{API}/users/me")
    assert response.status_code == 204
    assert not original.exists() and not derived.exists()
    assert store.count(name, mine) == 0

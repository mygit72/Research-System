"""Migrations must preserve data (not just produce the right schema)."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.core.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db = tmp_path / "migrate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    yield config, db
    get_settings.cache_clear()


def test_upgrade_preserves_document_version_links(alembic_at) -> None:  # type: ignore[no-untyped-def]
    config, db = alembic_at
    command.upgrade(config, "21233ea89d30")  # documents schema, before the index columns

    user, document, version = (uuid.uuid4().hex for _ in range(3))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO users (id, email, full_name, is_active, is_admin, preferences) "
            "VALUES (?, 'a@b.c', '', 1, 0, '{}')",
            (user,),
        )
        conn.execute(
            "INSERT INTO documents (id, user_id, title, title_is_user_set, status, doc_type, "
            "original_filename, warnings, authors_display) "
            "VALUES (?, ?, 'Paper', 0, 'ready', 'pdf', 'p.pdf', '[]', '')",
            (document, user),
        )
        conn.execute(
            "INSERT INTO document_versions (id, document_id, user_id, version_number, storage_key, "
            "file_hash, file_size, mime_type, original_filename, paginated, used_ocr, ocr_pages, "
            "processing_config, has_thumbnail) VALUES (?, ?, ?, 1, 'k', 'h', 1, 'application/pdf', "
            "'p.pdf', 1, 0, '[]', '{}', 0)",
            (version, document, user),
        )
        conn.execute(
            "UPDATE documents SET current_version_id = ? WHERE id = ?", (version, document)
        )

    command.upgrade(config, "head")

    with sqlite3.connect(db) as conn:
        current, index_status = conn.execute(
            "SELECT current_version_id, index_status FROM documents"
        ).fetchone()
        chunk_count = conn.execute("SELECT chunk_count FROM document_versions").fetchone()[0]
    assert current == version, "table rebuild must not null out foreign keys"
    assert index_status == "pending"
    assert chunk_count == 0

    # Downgrades rebuild tables on SQLite (drop column) -- the risky path.
    command.downgrade(config, "21233ea89d30")
    command.upgrade(config, "head")
    with sqlite3.connect(db) as conn:
        current = conn.execute("SELECT current_version_id FROM documents").fetchone()[0]
    assert current == version, "downgrade/upgrade round trip must keep foreign keys"

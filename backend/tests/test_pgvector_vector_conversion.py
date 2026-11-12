"""Regression test for a pgvector-specific bug that no other test could catch:
every existing test runs against SQLite, where `PgVectorStore` uses a plain
in-memory dict and never touches the real Postgres code path at all.

Root cause, found by reproducing live against production (the shared
Research Intelligence demo on Neon + pgvector): `register_vector(conn)`
makes psycopg deserialize a `vector` column into a `pgvector.Vector` object,
not a raw list/ndarray. `PgVectorStore.get_vector()` and `.get_vectors()`
did `np.asarray(row[0], dtype=np.float32)` on that object; numpy doesn't
know how to treat a `Vector` as array-like when an explicit dtype is given,
falls back to a scalar conversion, and raises
`TypeError: float() argument must be a string or a real number, not 'Vector'`.

`services/similarity.py`'s "similar papers" feature is the only caller of
`get_vector`/`get_vectors` (every other vector read goes through `.search()`,
which computes scores as plain floats inside the SQL expression and never
pulls a raw vector value into Python) -- which is why this was dormant until
that specific endpoint was hit on the live Postgres-backed demo.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import numpy as np
import pytest
from pgvector import Vector

from app.core.config import Settings
from app.services.vectorstore import PgVectorStore


@pytest.fixture
def pg_store(monkeypatch: pytest.MonkeyPatch) -> PgVectorStore:
    """A PgVectorStore whose is_sqlite check is forced False, so it takes the
    real psycopg code path, with `_get_connection` mocked to avoid a real DB."""
    settings = Settings(database_url="postgresql+asyncpg://fake/fake")
    store = PgVectorStore(settings)
    monkeypatch.setattr(type(settings), "is_sqlite", False, raising=False)
    return store


def _mock_connection(fetchone_row: tuple | None = None, fetchall_rows: list | None = None):
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_row
    cursor.fetchall.return_value = fetchall_rows or []

    @contextmanager
    def cursor_cm():
        yield cursor

    conn = MagicMock()
    conn.cursor.return_value = cursor_cm()

    @contextmanager
    def conn_cm():
        yield conn

    return conn_cm()


def test_get_vector_converts_pgvector_vector_type(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_vector = Vector([1.0, 2.0, 3.0, 4.0])
    monkeypatch.setattr(pg_store, "_get_connection", lambda: _mock_connection((raw_vector,)))

    result = pg_store.get_vector("documents__hashing-v1-384__384", uuid.uuid4())

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, [1.0, 2.0, 3.0, 4.0])


def test_get_vector_returns_none_for_missing_row(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pg_store, "_get_connection", lambda: _mock_connection(None))
    assert pg_store.get_vector("documents__hashing-v1-384__384", uuid.uuid4()) is None


def test_get_vectors_converts_pgvector_vector_type(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_id = uuid.uuid4()
    raw_vector = Vector([5.0, 6.0, 7.0])
    monkeypatch.setattr(
        pg_store, "_get_connection", lambda: _mock_connection(fetchall_rows=[(str(point_id), raw_vector)])
    )

    result = pg_store.get_vectors("documents__hashing-v1-384__384", [point_id])

    assert point_id in result
    assert isinstance(result[point_id], np.ndarray)
    assert result[point_id].dtype == np.float32
    np.testing.assert_array_equal(result[point_id], [5.0, 6.0, 7.0])

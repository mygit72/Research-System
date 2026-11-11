"""Dense vector index (Qdrant) behind a small interface.

- One collection per embedding model (`chunks__<model>__<dim>`), so switching
  models never mixes incompatible vector spaces.
- Every point carries its owner (`user_id`) and filterable metadata; user
  isolation is enforced *inside* the search filter, not after it.
- Local development uses Qdrant's embedded mode (a directory on disk); Docker
  uses the Qdrant server (QDRANT_URL). Embedded mode allows one process only,
  which matches the inline job backend.
"""

from __future__ import annotations

import contextlib
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from qdrant_client import QdrantClient, models

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "user_id": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "version_id": models.PayloadSchemaType.KEYWORD,
    "section_kind": models.PayloadSchemaType.KEYWORD,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "year": models.PayloadSchemaType.INTEGER,
}


@dataclass(slots=True)
class VectorPoint:
    id: uuid.UUID  # = chunk id (or document id for document vectors)
    vector: np.ndarray
    payload: dict[str, Any]


@dataclass(slots=True)
class VectorHit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any]


@dataclass(slots=True)
class VectorFilter:
    user_id: uuid.UUID
    document_ids: list[uuid.UUID] | None = None
    exclude_document_ids: list[uuid.UUID] | None = None
    version_ids: list[uuid.UUID] | None = None  # only these versions (e.g. current ones)
    section_kinds: list[str] | None = None
    exclude_section_kinds: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None


class VectorStore(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...
    def upsert(self, name: str, points: list[VectorPoint]) -> None: ...
    def delete(
        self,
        name: str,
        *,
        document_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> None: ...
    def search(
        self, name: str, vector: np.ndarray, flt: VectorFilter, limit: int
    ) -> list[VectorHit]: ...
    def collections(self) -> list[str]: ...
    def count(self, name: str, flt: VectorFilter | None = None) -> int: ...


def collection_name(kind: str, model_id: str, dimension: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", model_id.lower()).strip("-")
    return f"{kind}__{slug}__{dimension}"


def _to_filter(flt: VectorFilter, demo_user_id: uuid.UUID | None = None) -> models.Filter:
    if demo_user_id is not None and str(flt.user_id) != str(demo_user_id):
        user_match = models.MatchAny(any=[str(flt.user_id), str(demo_user_id)])
    else:
        user_match = models.MatchValue(value=str(flt.user_id))
    must: list[models.Condition] = [
        models.FieldCondition(key="user_id", match=user_match)
    ]
    must_not: list[models.Condition] = []
    if flt.document_ids:
        must.append(
            models.FieldCondition(
                key="document_id", match=models.MatchAny(any=[str(d) for d in flt.document_ids])
            )
        )
    if flt.exclude_document_ids:
        must_not.append(
            models.FieldCondition(
                key="document_id",
                match=models.MatchAny(any=[str(d) for d in flt.exclude_document_ids]),
            )
        )
    if flt.version_ids is not None:
        must.append(
            models.FieldCondition(
                key="version_id", match=models.MatchAny(any=[str(v) for v in flt.version_ids])
            )
        )
    if flt.section_kinds:
        must.append(
            models.FieldCondition(key="section_kind", match=models.MatchAny(any=flt.section_kinds))
        )
    if flt.exclude_section_kinds:
        must_not.append(
            models.FieldCondition(
                key="section_kind", match=models.MatchAny(any=flt.exclude_section_kinds)
            )
        )
    if flt.year_min is not None or flt.year_max is not None:
        must.append(
            models.FieldCondition(
                key="year", range=models.Range(gte=flt.year_min, lte=flt.year_max)
            )
        )
    return models.Filter(must=must, must_not=must_not or None)


class QdrantVectorStore:
    def __init__(
        self, client: QdrantClient, is_local: bool, demo_user_id: uuid.UUID | None = None
    ) -> None:
        self.client = client
        self.is_local = is_local
        self.demo_user_id = demo_user_id
        self._known: set[str] = set()
        self._lock = threading.Lock()
        # Embedded Qdrant persists through one SQLite connection and is not thread-safe:
        # concurrent indexing jobs and searches (all in worker threads) corrupted its
        # transactions ("cannot commit - no transaction is active"). Serialize every call
        # in embedded mode; the server handles concurrency itself.
        self._io: contextlib.AbstractContextManager[Any] = (
            threading.RLock() if is_local else contextlib.nullcontext()
        )

    def ensure_collection(self, name: str, dimension: int) -> None:
        with self._lock, self._io:
            if name in self._known:
                return
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    name,
                    vectors_config=models.VectorParams(
                        size=dimension, distance=models.Distance.COSINE
                    ),
                )
                if not self.is_local:  # payload indexes are a server feature
                    for field, schema in PAYLOAD_INDEXES.items():
                        self.client.create_payload_index(name, field, field_schema=schema)
                log.info("vector_collection_created", collection=name, dimension=dimension)
            self._known.add(name)

    def upsert(self, name: str, points: list[VectorPoint]) -> None:
        for start in range(0, len(points), 256):
            batch = points[start : start + 256]
            with self._io:
                self.client.upsert(
                    name,
                    points=[
                        models.PointStruct(
                            id=str(p.id), vector=p.vector.tolist(), payload=p.payload
                        )
                        for p in batch
                    ],
                    wait=True,
                )

    def delete(
        self,
        name: str,
        *,
        document_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> None:
        key, value = ("version_id", version_id) if version_id else ("document_id", document_id)
        if value is None:
            raise ValueError("delete needs document_id or version_id")
        with self._io:
            if not self.client.collection_exists(name):
                return
            self.client.delete(
                name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=key, match=models.MatchValue(value=str(value))
                            )
                        ]
                    )
                ),
                wait=True,
            )

    def search(
        self, name: str, vector: np.ndarray, flt: VectorFilter, limit: int
    ) -> list[VectorHit]:
        with self._io:
            if not self.client.collection_exists(name):
                return []
            result = self.client.query_points(
                name,
                query=vector.tolist(),
                query_filter=_to_filter(flt, self.demo_user_id),
                limit=limit,
                with_payload=True,
            )
        return [
            VectorHit(
                id=uuid.UUID(str(point.id)), score=float(point.score), payload=point.payload or {}
            )
            for point in result.points
        ]

    def get_vector(self, name: str, point_id: uuid.UUID) -> np.ndarray | None:
        with self._io:
            if not self.client.collection_exists(name):
                return None
            points = self.client.retrieve(name, ids=[str(point_id)], with_vectors=True)
        if not points or points[0].vector is None:
            return None
        return np.asarray(points[0].vector, dtype=np.float32)

    def get_vectors(self, name: str, point_ids: list[uuid.UUID]) -> dict[uuid.UUID, np.ndarray]:
        found: dict[uuid.UUID, np.ndarray] = {}
        for start in range(0, len(point_ids), 256):
            batch = [str(p) for p in point_ids[start : start + 256]]
            with self._io:
                if not self.client.collection_exists(name):
                    return {}
                points = self.client.retrieve(name, ids=batch, with_vectors=True)
            for point in points:
                if point.vector is not None:
                    found[uuid.UUID(str(point.id))] = np.asarray(point.vector, dtype=np.float32)
        return found

    def collections(self) -> list[str]:
        with self._io:
            return [c.name for c in self.client.get_collections().collections]

    def count(self, name: str, flt: VectorFilter | None = None) -> int:
        with self._io:
            if not self.client.collection_exists(name):
                return 0
            return self.client.count(
                name, count_filter=_to_filter(flt, self.demo_user_id) if flt else None, exact=True
            ).count

    def close(self) -> None:
        with contextlib.suppress(Exception), self._io:
            self.client.close()


class PgVectorStore:
    """PostgreSQL pgvector storage implementing the VectorStore protocol.

    Stores dense embeddings and metadata directly in PostgreSQL, eliminating
    the separate vector DB service on serverless and free-tier environments (e.g. Neon).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.table_name = "vector_points"
        self._lock = threading.Lock()
        self._known: set[str] = set()
        # In-memory dictionary fallback when running on SQLite in tests
        self._mem_points: dict[str, dict[uuid.UUID, VectorPoint]] = {}

    def _get_connection(self) -> Any:
        import psycopg
        from pgvector.psycopg import register_vector

        raw_url = self.settings.database_url
        clean_url = re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", raw_url)
        conn = psycopg.connect(clean_url, autocommit=True)
        register_vector(conn)
        return conn

    def ensure_collection(self, name: str, dimension: int) -> None:
        with self._lock:
            if name in self._known:
                return
            if self.settings.is_sqlite:
                self._mem_points.setdefault(name, {})
                self._known.add(name)
                return

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self.table_name} (
                            collection_name VARCHAR(120) NOT NULL,
                            id UUID NOT NULL,
                            user_id UUID NOT NULL,
                            document_id UUID,
                            version_id UUID,
                            section_kind VARCHAR(60),
                            doc_type VARCHAR(60),
                            year INTEGER,
                            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            vector vector({dimension}),
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            PRIMARY KEY (collection_name, id)
                        );
                        """
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS ix_{self.table_name}_lookup "
                        f"ON {self.table_name} (collection_name, user_id);"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS ix_{self.table_name}_doc "
                        f"ON {self.table_name} (collection_name, document_id);"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS ix_{self.table_name}_ver "
                        f"ON {self.table_name} (collection_name, version_id);"
                    )
            self._known.add(name)
            log.info("pgvector_collection_ensured", collection=name, dimension=dimension)

    def upsert(self, name: str, points: list[VectorPoint]) -> None:
        if not points:
            return
        if self.settings.is_sqlite:
            col = self._mem_points.setdefault(name, {})
            for p in points:
                col[p.id] = p
            return

        import json

        rows = []
        for p in points:
            payload = p.payload or {}
            user_id = payload.get("user_id")
            document_id = payload.get("document_id")
            version_id = payload.get("version_id")
            section_kind = payload.get("section_kind")
            doc_type = payload.get("doc_type")
            year = payload.get("year")
            rows.append(
                (
                    name,
                    str(p.id),
                    str(user_id) if user_id else None,
                    str(document_id) if document_id else None,
                    str(version_id) if version_id else None,
                    str(section_kind) if section_kind else None,
                    str(doc_type) if doc_type else None,
                    int(year) if year is not None else None,
                    json.dumps(payload),
                    p.vector,
                )
            )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {self.table_name} (
                        collection_name, id, user_id, document_id, version_id,
                        section_kind, doc_type, year, payload, vector
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (collection_name, id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        document_id = EXCLUDED.document_id,
                        version_id = EXCLUDED.version_id,
                        section_kind = EXCLUDED.section_kind,
                        doc_type = EXCLUDED.doc_type,
                        year = EXCLUDED.year,
                        payload = EXCLUDED.payload,
                        vector = EXCLUDED.vector;
                    """,
                    rows,
                )

    def delete(
        self,
        name: str,
        *,
        document_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> None:
        if self.settings.is_sqlite:
            col = self._mem_points.get(name, {})
            to_del = []
            for pid, pt in col.items():
                p = pt.payload or {}
                if document_id and p.get("document_id") == str(document_id):
                    to_del.append(pid)
                elif version_id and p.get("version_id") == str(version_id):
                    to_del.append(pid)
            for pid in to_del:
                col.pop(pid, None)
            return

        key, val = ("version_id", version_id) if version_id else ("document_id", document_id)
        if val is None:
            return
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE collection_name = %s AND {key} = %s",
                    (name, str(val)),
                )

    def search(
        self, name: str, vector: np.ndarray, flt: VectorFilter, limit: int
    ) -> list[VectorHit]:
        if self.settings.is_sqlite:
            col = self._mem_points.get(name, {})
            hits: list[VectorHit] = []
            q_norm = np.linalg.norm(vector)
            if q_norm == 0:
                return []
            for pid, pt in col.items():
                pl = pt.payload or {}
                uid = pl.get("user_id")
                demo_id = str(self.settings.demo_user_id) if self.settings.demo_mode else None
                if uid != str(flt.user_id) and (demo_id is None or uid != demo_id):
                    continue
                if flt.document_ids and pl.get("document_id") not in [str(d) for d in flt.document_ids]:
                    continue
                if flt.exclude_document_ids and pl.get("document_id") in [str(d) for d in flt.exclude_document_ids]:
                    continue
                if flt.version_ids and pl.get("version_id") not in [str(v) for v in flt.version_ids]:
                    continue
                if flt.section_kinds and pl.get("section_kind") not in flt.section_kinds:
                    continue
                if flt.exclude_section_kinds and pl.get("section_kind") in flt.exclude_section_kinds:
                    continue
                year = pl.get("year")
                if year is not None:
                    if flt.year_min is not None and int(year) < flt.year_min:
                        continue
                    if flt.year_max is not None and int(year) > flt.year_max:
                        continue
                p_norm = np.linalg.norm(pt.vector)
                sim = float(np.dot(vector, pt.vector) / (q_norm * p_norm)) if p_norm > 0 else 0.0
                hits.append(VectorHit(id=pid, score=sim, payload=pl))
            hits.sort(key=lambda h: h.score, reverse=True)
            return hits[:limit]

        import psycopg.errors

        clauses = ["collection_name = %s"]
        params: list[Any] = [name]

        if self.settings.demo_mode and self.settings.demo_user_id:
            clauses.append("(user_id = %s OR user_id = %s)")
            params.extend([str(flt.user_id), str(self.settings.demo_user_id)])
        else:
            clauses.append("user_id = %s")
            params.append(str(flt.user_id))

        if flt.document_ids:
            clauses.append("document_id = ANY(%s)")
            params.append([str(d) for d in flt.document_ids])
        if flt.exclude_document_ids:
            clauses.append("document_id != ALL(%s)")
            params.append([str(d) for d in flt.exclude_document_ids])
        if flt.version_ids is not None:
            clauses.append("version_id = ANY(%s)")
            params.append([str(v) for v in flt.version_ids])
        if flt.section_kinds:
            clauses.append("section_kind = ANY(%s)")
            params.append(list(flt.section_kinds))
        if flt.exclude_section_kinds:
            clauses.append("section_kind != ALL(%s)")
            params.append(list(flt.exclude_section_kinds))
        if flt.year_min is not None:
            clauses.append("year >= %s")
            params.append(flt.year_min)
        if flt.year_max is not None:
            clauses.append("year <= %s")
            params.append(flt.year_max)

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT id, (1.0 - (vector <=> %s)) AS score, payload
            FROM {self.table_name}
            WHERE {where_sql}
            ORDER BY vector <=> %s ASC
            LIMIT %s;
        """
        full_params = [vector] + params + [vector, limit]

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, full_params)
                    rows = cur.fetchall()
            return [
                VectorHit(
                    id=uuid.UUID(str(r[0])),
                    score=float(r[1]),
                    payload=r[2] if isinstance(r[2], dict) else {},
                )
                for r in rows
            ]
        except psycopg.errors.UndefinedTable:
            return []

    def collections(self) -> list[str]:
        if self.settings.is_sqlite:
            return list(self._mem_points.keys())
        import psycopg.errors

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT DISTINCT collection_name FROM {self.table_name};")
                    return [r[0] for r in cur.fetchall()]
        except psycopg.errors.UndefinedTable:
            return []

    def count(self, name: str, flt: VectorFilter | None = None) -> int:
        if self.settings.is_sqlite:
            return len(self._mem_points.get(name, {}))
        import psycopg.errors

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if flt is None:
                        cur.execute(
                            f"SELECT count(*) FROM {self.table_name} WHERE collection_name = %s;",
                            (name,),
                        )
                    else:
                        cur.execute(
                            f"SELECT count(*) FROM {self.table_name} WHERE collection_name = %s AND user_id = %s;",
                            (name, str(flt.user_id)),
                        )
                    row = cur.fetchone()
                    return int(row[0]) if row else 0
        except psycopg.errors.UndefinedTable:
            return 0

    def get_vector(self, name: str, point_id: uuid.UUID) -> np.ndarray | None:
        if self.settings.is_sqlite:
            pt = self._mem_points.get(name, {}).get(point_id)
            return pt.vector if pt else None
        import psycopg.errors

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT vector FROM {self.table_name} WHERE collection_name = %s AND id = %s;",
                        (name, str(point_id)),
                    )
                    row = cur.fetchone()
                    if not row or row[0] is None:
                        return None
                    return np.asarray(row[0], dtype=np.float32)
        except psycopg.errors.UndefinedTable:
            return None

    def get_vectors(self, name: str, point_ids: list[uuid.UUID]) -> dict[uuid.UUID, np.ndarray]:
        if not point_ids:
            return {}
        if self.settings.is_sqlite:
            col = self._mem_points.get(name, {})
            return {
                pid: col[pid].vector
                for pid in point_ids
                if pid in col and col[pid].vector is not None
            }
        import psycopg.errors

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id, vector FROM {self.table_name} WHERE collection_name = %s AND id = ANY(%s);",
                        (name, [str(pid) for pid in point_ids]),
                    )
                    rows = cur.fetchall()
            return {
                uuid.UUID(str(r[0])): np.asarray(r[1], dtype=np.float32)
                for r in rows
                if r[1] is not None
            }
        except psycopg.errors.UndefinedTable:
            return {}

    def close(self) -> None:
        pass


_store: VectorStore | None = None
_store_key: str | None = None
_store_lock = threading.Lock()


def get_vector_store(settings: Settings) -> VectorStore:
    """Process-wide store (Qdrant or pgvector depending on settings)."""
    global _store, _store_key
    if settings.vector_store == "pgvector":
        key = f"pgvector:{settings.database_url}"
        with _store_lock:
            if _store is None or _store_key != key:
                if _store is not None:
                    close_vector_store()
                _store = PgVectorStore(settings)
                _store_key = key
            return _store

    key = settings.qdrant_url or str(Path(settings.storage_dir, "qdrant").resolve())
    with _store_lock:
        if _store is None or _store_key != key:
            if _store is not None:
                close_vector_store()
            demo_user = settings.demo_user_id if settings.demo_mode else None
            if settings.qdrant_url:
                client = QdrantClient(url=settings.qdrant_url, timeout=30)
                _store = QdrantVectorStore(client, is_local=False, demo_user_id=demo_user)
            else:
                Path(key).mkdir(parents=True, exist_ok=True)
                _store = QdrantVectorStore(
                    QdrantClient(path=key), is_local=True, demo_user_id=demo_user
                )
            _store_key = key
        return _store


def close_vector_store() -> None:
    global _store, _store_key
    if _store is not None:
        if hasattr(_store, "close"):
            _store.close()
    _store, _store_key = None, None

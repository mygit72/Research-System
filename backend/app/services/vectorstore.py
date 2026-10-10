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


def _to_filter(flt: VectorFilter) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="user_id", match=models.MatchValue(value=str(flt.user_id)))
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
    def __init__(self, client: QdrantClient, is_local: bool) -> None:
        self.client = client
        self.is_local = is_local
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
                query_filter=_to_filter(flt),
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
                name, count_filter=_to_filter(flt) if flt else None, exact=True
            ).count


_store: QdrantVectorStore | None = None
_store_key: str | None = None
_store_lock = threading.Lock()


def get_vector_store(settings: Settings) -> QdrantVectorStore:
    """Process-wide store (embedded Qdrant allows a single client per directory)."""
    global _store, _store_key
    key = settings.qdrant_url or str(Path(settings.storage_dir, "qdrant").resolve())
    with _store_lock:
        if _store is None or _store_key != key:
            if _store is not None:
                close_vector_store()
            if settings.qdrant_url:
                client = QdrantClient(url=settings.qdrant_url, timeout=30)
                _store = QdrantVectorStore(client, is_local=False)
            else:
                Path(key).mkdir(parents=True, exist_ok=True)
                _store = QdrantVectorStore(QdrantClient(path=key), is_local=True)
            _store_key = key
        return _store


def close_vector_store() -> None:
    global _store, _store_key
    if _store is not None:
        with contextlib.suppress(Exception), _store._io:
            _store.client.close()
    _store, _store_key = None, None

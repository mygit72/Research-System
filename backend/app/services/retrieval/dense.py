"""Dense retrieval: embed the query, nearest neighbours in Qdrant, filters inside the ANN search.

Filters (user, current versions, papers, section kinds) are part of the Qdrant
query, so the k nearest neighbours are the k nearest *allowed* passages. Filtering
afterwards would silently return fewer results.
"""

from __future__ import annotations

import asyncio

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import NamedCache, digest
from app.core.config import Settings
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.retrieval.types import RetrievedPassage, SearchScope
from app.services.vectorstore import VectorFilter, collection_name, get_vector_store

# Query embeddings are cached: people re-run and refine the same searches.
_query_cache: NamedCache[np.ndarray] = NamedCache(
    "query_embeddings",
    512,
    encode=lambda v: np.asarray(v, dtype=np.float32).tobytes(),
    decode=lambda b: np.frombuffer(b, dtype=np.float32),
)


def embed_query(provider: EmbeddingProvider, query: str) -> np.ndarray:
    key = digest(provider.model_id, query)
    cached = _query_cache.get(key)
    if cached is not None:
        return cached
    vector = provider.embed_query(query)
    _query_cache.set(key, vector)
    return vector


class DenseRetriever:
    name = "dense"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_id(self) -> str:
        return get_embedding_provider(self.settings).model_id

    async def search(
        self, session: AsyncSession, scope: SearchScope, query: str, limit: int
    ) -> list[RetrievedPassage]:
        provider = get_embedding_provider(self.settings)
        # Only versions embedded with the current model live in this model's collection.
        versions = [
            vid for vid, v in scope.versions.items() if v.embedding_model == provider.model_id
        ]
        if not versions or scope.is_empty:
            return []
        vector = await asyncio.to_thread(embed_query, provider, query)
        name = collection_name("chunks", provider.model_id, int(vector.shape[0]))
        flt = VectorFilter(
            user_id=scope.user_id,
            version_ids=versions,
            document_ids=list(scope.allowed_documents) if scope.allowed_documents else None,
            section_kinds=sorted(scope.section_kinds) if scope.section_kinds else None,
            exclude_section_kinds=sorted(scope.exclude_section_kinds) or None,
        )
        store = get_vector_store(self.settings)
        hits = await asyncio.to_thread(store.search, name, vector, flt, limit)
        return [RetrievedPassage(hit.id, hit.score) for hit in hits]

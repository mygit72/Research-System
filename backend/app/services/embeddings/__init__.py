"""Embedding providers, selected by configuration (EMBEDDING_PROVIDER / EMBEDDING_MODEL)."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.services.embeddings.base import EmbeddingError, EmbeddingProvider, l2_normalize
from app.services.embeddings.hashing import HashingEmbeddingProvider
from app.services.embeddings.local import SentenceTransformerProvider
from app.services.embeddings.remote import OpenAICompatibleEmbeddingProvider
from app.services.models.manager import model_manager


@lru_cache(maxsize=8)
def _build(
    provider: str,
    model: str,
    device: str,
    dtype: str,
    batch_size: int,
    api_key: str,
    base_url: str,
    dimension: int,
    local_only: bool,
) -> EmbeddingProvider:
    if provider == "hashing":
        return HashingEmbeddingProvider(dimension=dimension or 384)
    if provider == "sentence_transformers":
        return SentenceTransformerProvider(
            model, model_manager, device=device, dtype=dtype, batch_size=batch_size
        )
    if provider == "openai":
        if local_only:
            raise ServiceUnavailableError(
                "Remote embedding providers are disabled (LOCAL_ONLY=true).",
                hint="Use a local embedding model or turn off local-only mode.",
            )
        if not api_key:
            raise ServiceUnavailableError("EMBEDDING_API_KEY is not configured.")
        return OpenAICompatibleEmbeddingProvider(
            model, api_key, base_url=base_url, dimension=dimension or 1536
        )
    raise ServiceUnavailableError(f"Unknown embedding provider “{provider}”.")


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return _build(
        settings.embedding_provider,
        settings.embedding_model,
        settings.model_device,
        settings.model_dtype,
        settings.embedding_batch_size,
        settings.embedding_api_key.get_secret_value() if settings.embedding_api_key else "",
        settings.embedding_api_base,
        settings.embedding_dimension,
        settings.local_only,
    )


__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "SentenceTransformerProvider",
    "get_embedding_provider",
    "l2_normalize",
]

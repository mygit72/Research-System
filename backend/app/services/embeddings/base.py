from __future__ import annotations

from typing import Protocol

import numpy as np


class EmbeddingError(Exception):
    """Embedding failed (model unavailable, remote error). `user_message` is safe to show."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class EmbeddingProvider(Protocol):
    """Turns text into L2-normalized vectors.

    `model_id` is recorded with every stored vector and names the vector
    collection, so vectors from different models are never compared.
    """

    model_id: str
    dimension: int
    max_tokens: int
    is_remote: bool

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.clip(norms, 1e-12, None)).astype(np.float32)

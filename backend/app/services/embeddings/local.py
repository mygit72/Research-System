"""sentence-transformers embeddings (BGE, E5, MiniLM, ...), run locally.

Asymmetric retrieval models expect different prefixes for queries and
passages; using the wrong one (or none) measurably hurts recall.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.services.embeddings.base import EmbeddingError, l2_normalize
from app.services.models.manager import ModelManager, resolve_device, resolve_dtype

# model-name substring -> (query prefix, passage prefix)
PREFIXES: list[tuple[str, tuple[str, str]]] = [
    ("bge-", ("Represent this sentence for searching relevant passages: ", "")),
    ("e5-", ("query: ", "passage: ")),
    ("gte-", ("", "")),
    ("nomic-embed", ("search_query: ", "search_document: ")),
]


def prefixes_for(model_name: str) -> tuple[str, str]:
    lowered = model_name.lower()
    for key, prefixes in PREFIXES:
        if key in lowered:
            return prefixes
    return "", ""


class SentenceTransformerProvider:
    is_remote = False

    def __init__(
        self,
        model_name: str,
        manager: ModelManager,
        device: str = "auto",
        dtype: str = "auto",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.model_id = model_name
        self.manager = manager
        self.device = resolve_device(device)
        self.dtype = resolve_dtype(dtype, self.device)
        self.batch_size = batch_size
        self.query_prefix, self.passage_prefix = prefixes_for(model_name)
        self._dimension: int | None = None
        self._max_tokens: int | None = None

    def _model(self) -> Any:
        def load() -> Any:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on install
                raise EmbeddingError(
                    "Local embedding models aren't installed on this server.",
                    detail="pip install -e '.[ml]'",
                ) from exc
            try:
                model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as exc:
                raise EmbeddingError(
                    f"The embedding model “{self.model_name}” couldn't be loaded.",
                    detail=repr(exc),
                ) from exc
            if self.dtype == "float16":
                model = model.half()
            return model

        return self.manager.get(f"embed:{self.model_name}:{self.device}:{self.dtype}", load)

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            model = self._model()
            getter = (
                getattr(model, "get_embedding_dimension", None)
                or model.get_sentence_embedding_dimension
            )
            self._dimension = int(getter())
        return self._dimension

    @property
    def max_tokens(self) -> int:
        if self._max_tokens is None:
            self._max_tokens = int(self._model().max_seq_length)
        return self._max_tokens

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        try:
            vectors = self._model().encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Embedding failed.", detail=repr(exc)) from exc
        return l2_normalize(np.asarray(vectors, dtype=np.float32))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode([self.passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self.query_prefix + text])[0]

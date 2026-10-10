"""OpenAI-compatible embeddings API (OpenAI, Azure-compatible gateways, vLLM, LM Studio...)."""

from __future__ import annotations

import time

import httpx
import numpy as np

from app.services.embeddings.base import EmbeddingError, l2_normalize

MAX_BATCH = 96
RETRIES = 3


class OpenAICompatibleEmbeddingProvider:
    is_remote = True

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        dimension: int = 1536,
        max_tokens: int = 8191,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = model_name
        self.dimension = dimension
        self.max_tokens = max_tokens
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def _request(self, texts: list[str]) -> np.ndarray:
        for attempt in range(RETRIES):
            try:
                response = self._client.post(
                    "/embeddings", json={"model": self.model_id, "input": texts}
                )
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise EmbeddingError(
                        "The embedding service is unreachable.", detail=repr(exc)
                    ) from exc
                time.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == RETRIES - 1:
                    raise EmbeddingError(
                        "The embedding service is busy. Please try again later.",
                        detail=f"HTTP {response.status_code}",
                    )
                time.sleep(float(response.headers.get("retry-after", 2**attempt)))
                continue
            if response.status_code >= 400:
                raise EmbeddingError(
                    "The embedding service rejected the request.",
                    detail=f"HTTP {response.status_code}: {response.text[:300]}",
                )
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            return np.asarray([item["embedding"] for item in data], dtype=np.float32)
        raise EmbeddingError("Embedding failed.")  # pragma: no cover

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        parts = [self._request(texts[i : i + MAX_BATCH]) for i in range(0, len(texts), MAX_BATCH)]
        return l2_normalize(np.concatenate(parts))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

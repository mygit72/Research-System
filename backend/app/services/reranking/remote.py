"""Rerank APIs with the common `/rerank` shape (Cohere, Jina, Voyage, self-hosted TEI/Infinity).

POST {base}/rerank  {"model", "query", "documents": [str], "top_n"}
→    {"results": [{"index": int, "relevance_score": float}, ...]}
"""

from __future__ import annotations

import time

import httpx

from app.services.reranking.base import RerankError

MAX_DOCUMENTS = 100
RETRIES = 3


class ApiReranker:
    is_remote = True

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id = model_name
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def _request(self, query: str, documents: list[str]) -> list[float]:
        body = {"model": self.model_id, "query": query, "documents": documents}
        body["top_n"] = len(documents)
        for attempt in range(RETRIES):
            try:
                response = self._client.post("/rerank", json=body)
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise RerankError(
                        "The reranking service is unreachable.", detail=repr(exc)
                    ) from exc
                time.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == RETRIES - 1:
                    raise RerankError(
                        "The reranking service is busy. Please try again later.",
                        detail=f"HTTP {response.status_code}",
                    )
                time.sleep(float(response.headers.get("retry-after", 2**attempt)))
                continue
            if response.status_code >= 400:
                raise RerankError(
                    "The reranking service rejected the request.",
                    detail=f"HTTP {response.status_code}: {response.text[:300]}",
                )
            scores = [0.0] * len(documents)
            for item in response.json()["results"]:
                scores[int(item["index"])] = float(item["relevance_score"])
            return scores
        raise RerankError("Reranking failed.")  # pragma: no cover

    def score(self, query: str, passages: list[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), MAX_DOCUMENTS):
            scores.extend(self._request(query, passages[start : start + MAX_DOCUMENTS]))
        return scores

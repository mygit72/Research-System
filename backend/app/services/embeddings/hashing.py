"""Feature-hashing embeddings: a real, dependency-free lexical baseline.

Each text becomes a sparse bag of unigrams and bigrams hashed into `dimension`
buckets (signed hashing to reduce collision bias), weighted by sublinear term
frequency, then L2-normalized. It captures lexical overlap, not meaning, so it
is used for tests, offline development and as a baseline in retrieval
experiments — never presented as a semantic model.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections import Counter

import numpy as np

from app.services.embeddings.base import l2_normalize

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "which",
        "with",
        "we",
        "our",
        "their",
        "these",
        "those",
        "can",
        "not",
    ]
)


def _features(text: str) -> Counter[str]:
    tokens = [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]
    features: Counter[str] = Counter(tokens)
    features.update(f"{a} {b}" for a, b in itertools.pairwise(tokens))
    return features


class HashingEmbeddingProvider:
    is_remote = False
    max_tokens = 100_000

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.model_id = f"hashing-v1-{dimension}"

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for feature, count in _features(text).items():
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimension
            sign = 1.0 if (value >> 63) & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        return vector

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return l2_normalize(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

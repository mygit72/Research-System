"""Token counting for chunk sizing.

Chunk limits must be in the *embedding model's* tokens (BGE truncates at 512),
so the default counter uses that model's tokenizer. An approximate counter is
used when no tokenizer is available (tests, offline) and is deliberately
conservative (overestimates) so chunks never exceed the real limit.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Protocol

_WORDISH = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...

    def spans(self, text: str) -> list[tuple[int, int]]:
        """Character spans of each token (used for exact token windows)."""
        ...


class ApproximateTokenCounter:
    """~1.3 tokens per word-piece; punctuation counts as its own token."""

    name = "approximate"

    def count(self, text: str) -> int:
        return sum(1 + len(m.group(0)) // 6 for m in _WORDISH.finditer(text))

    def spans(self, text: str) -> list[tuple[int, int]]:
        # One span per counted token (long words become several), so len(spans) == count.
        spans: list[tuple[int, int]] = []
        for m in _WORDISH.finditer(text):
            start, end = m.start(), m.end()
            pieces = 1 + (end - start) // 6
            step = max(1, (end - start) // pieces)
            for i in range(pieces):
                spans.append((start + i * step, end if i == pieces - 1 else start + (i + 1) * step))
        return spans


class HFTokenCounter:
    def __init__(self, model_name: str) -> None:
        from transformers import AutoTokenizer

        self.name = f"hf:{model_name}"
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)

    def count(self, text: str) -> int:
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])

    def spans(self, text: str) -> list[tuple[int, int]]:
        encoded = self._tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [tuple(span) for span in encoded["offset_mapping"]]  # type: ignore[misc]


@lru_cache(maxsize=4)
def get_token_counter(model_name: str | None) -> TokenCounter:
    if model_name:
        try:
            return HFTokenCounter(model_name)
        except Exception:  # tokenizer unavailable offline: stay conservative
            pass
    return ApproximateTokenCounter()

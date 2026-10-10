"""Retrieval metrics against expected evidence spans (pure functions, no I/O).

Relevance is decided per passage: a retrieved passage is relevant to an expected span when
it is from the same paper version and their character ranges overlap — or, if the paper was
reprocessed since the question was written (different version), when the passage contains
the start of the expected quote. Chunk ids are never compared, so different chunkings and
embedding models are measured on the same ground truth.

Definitions (K = cutoff, S = expected spans of a question):
- **Recall@K**: share of S covered by at least one of the top-K passages.
- **Precision@K**: share of the top K passages relevant to some span in S (divided by K, so
  returning fewer than K passages doesn't inflate it).
- **MRR**: 1 / rank of the first relevant passage (0 if none in the list).
- **nDCG@K**: binary gains, but a passage gains only for a span not covered by an earlier
  passage (so three chunks of the same paragraph don't count three times);
  IDCG = Σ_{i ≤ min(K, |S|)} 1 / log2(i + 1).
- **Paper recall@K**: share of the expected papers among the papers of the top K passages.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

QUOTE_PROBE = 60  # characters of the expected quote looked for after reprocessing


@dataclass(frozen=True)
class Span:
    document_id: str
    version_id: str
    char_start: int
    char_end: int
    quote: str = ""


@dataclass(frozen=True)
class Passage:
    document_id: str
    version_id: str
    char_start: int
    char_end: int
    text: str = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def covers(passage: Passage, span: Span) -> bool:
    if passage.document_id != span.document_id:
        return False
    if passage.version_id == span.version_id:
        return min(passage.char_end, span.char_end) > max(passage.char_start, span.char_start)
    probe = _norm(span.quote)[:QUOTE_PROBE]
    return bool(probe) and probe in _norm(passage.text)


def _covered(passages: Sequence[Passage], spans: Sequence[Span]) -> list[set[int]]:
    """For each passage: the indices of the spans it covers."""
    return [{i for i, span in enumerate(spans) if covers(p, span)} for p in passages]


def recall_at_k(passages: Sequence[Passage], spans: Sequence[Span], k: int) -> float:
    if not spans:
        return 0.0
    found = set().union(*_covered(passages[:k], spans)) if passages[:k] else set()
    return len(found) / len(spans)


def precision_at_k(passages: Sequence[Passage], spans: Sequence[Span], k: int) -> float:
    if k <= 0:
        return 0.0
    return sum(1 for c in _covered(passages[:k], spans) if c) / k


def reciprocal_rank(passages: Sequence[Passage], spans: Sequence[Span]) -> float:
    for rank, covered in enumerate(_covered(passages, spans), 1):
        if covered:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(passages: Sequence[Passage], spans: Sequence[Span], k: int) -> float:
    if not spans:
        return 0.0
    seen: set[int] = set()
    dcg = 0.0
    for rank, covered in enumerate(_covered(passages[:k], spans), 1):
        new = covered - seen
        if new:
            dcg += 1.0 / math.log2(rank + 1)
            seen |= new
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(spans)) + 1))
    return dcg / ideal if ideal else 0.0


def paper_recall_at_k(passages: Sequence[Passage], spans: Sequence[Span], k: int) -> float:
    expected = {s.document_id for s in spans}
    if not expected:
        return 0.0
    return len(expected & {p.document_id for p in passages[:k]}) / len(expected)


def retrieval_metrics(
    passages: Sequence[Passage], spans: Sequence[Span], ks: Sequence[int] = (1, 3, 5, 10)
) -> dict[str, float]:
    out: dict[str, float] = {"mrr": round(reciprocal_rank(passages, spans), 4)}
    for k in ks:
        out[f"recall@{k}"] = round(recall_at_k(passages, spans, k), 4)
        out[f"precision@{k}"] = round(precision_at_k(passages, spans, k), 4)
        out[f"ndcg@{k}"] = round(ndcg_at_k(passages, spans, k), 4)
        out[f"paper_recall@{k}"] = round(paper_recall_at_k(passages, spans, k), 4)
    return out


def mean(rows: Sequence[dict[str, float | None]]) -> dict[str, float]:
    """Average each metric over the rows that have it (None = not applicable)."""
    keys = {k for row in rows for k, v in row.items() if isinstance(v, int | float)}
    out = {}
    for key in sorted(keys):
        values = [float(v) for row in rows if isinstance(v := row.get(key), int | float)]
        if values:
            out[key] = round(sum(values) / len(values), 4)
    return out


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[index], 1)

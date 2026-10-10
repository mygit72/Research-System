"""Metrics for the experiments. Standard library only; every function is small enough to check by hand.

Four families:

* **answer metrics** compare a predicted answer string with the accepted answers
  (accuracy, exact match, token F1, contains, abstention rate);
* **retrieval metrics** compare a ranked list of passage indices with the indices of the
  relevant passages (recall@k, precision@k, hit rate@k, MRR, nDCG@k — binary relevance);
* **grounded metrics** compare a generated answer with the passages the generator was given
  (groundedness — a lexical proxy, see its docstring for what it does and does not show).
* **evidence metrics** read which passages an answer was made from (retrieval rate — how often a
  system that may skip retrieval actually retrieved).

`expand_metric` turns a name from your plan ("Recall@k", "Exact match", "MRR") into the
concrete metrics to compute. A name it doesn't know raises `UnknownMetric`: add it here
rather than letting a made-up number into your results.
"""

from __future__ import annotations

import math
import re
import string
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

DEFAULT_KS = (1, 5, 10)


class UnknownMetric(Exception):
    pass


# --- answer metrics --------------------------------------------------------------------------


def normalize_answer(text: str) -> str:
    """Lowercase, drop punctuation and articles, collapse spaces (the SQuAD convention)."""
    text = "".join(ch for ch in text.lower() if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact_match(prediction: str, answers: Sequence[str]) -> float:
    return float(any(normalize_answer(prediction) == normalize_answer(a) for a in answers))


def accuracy(prediction: str, answers: Sequence[str]) -> float:
    """For labels: equal after trimming and lowercasing (no article / punctuation stripping)."""
    return float(any(prediction.strip().lower() == a.strip().lower() for a in answers))


def token_f1(prediction: str, answers: Sequence[str]) -> float:
    """Best F1 over the accepted answers, on bags of normalized tokens."""
    best = 0.0
    predicted = normalize_answer(prediction).split()
    for answer in answers:
        gold = normalize_answer(answer).split()
        overlap = sum((Counter(predicted) & Counter(gold)).values())
        if overlap == 0:
            continue
        precision, recall = overlap / len(predicted), overlap / len(gold)
        best = max(best, 2 * precision * recall / (precision + recall))
    return best


ABSTAIN = "unanswerable"  # what a generator is told to say when it cannot answer (generation.py)

_STOPWORDS = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "by",
        "with",
        "as",
        "it",
        "its",
        "this",
        "that",
        "from",
        "which",
        "what",
        "who",
        "how",
        "why",
        "when",
        "where",
        "do",
        "does",
        "did",
        "not",
        "no",
        "yes",
    ]
)


def is_abstention(prediction: str) -> bool:
    return normalize_answer(prediction) == ABSTAIN


def abstention(prediction: str, answers: Sequence[str]) -> float:
    """1 if the system said it can't answer. Not a quality score: it tells you how much of a low
    exact match comes from declining rather than from being wrong."""
    return float(is_abstention(prediction))


def contains(prediction: str, answers: Sequence[str]) -> float:
    """1 if an accepted answer appears in the prediction as whole words. Lenient on purpose: a
    language model writes "It was Denver Broncos who won" where exact match wants "Denver
    Broncos". Report it next to exact match, never instead of it."""
    padded = f" {normalize_answer(prediction)} "
    wanted = (normalize_answer(a) for a in answers)
    return float(any(w and f" {w} " in padded for w in wanted))


def groundedness(answer: str, context: Sequence[str]) -> float:
    """The share of the answer's content words that occur in the passages the generator was
    given. A *lexical proxy*: it catches an answer that brings in words the passages never
    contain, and misses one that rearranges true words into a false claim. It is NOT faithfulness
    — that needs an entailment model or a judge. An abstention ("unanswerable") states nothing, so
    it scores 1.0; an answer with no content words does too."""
    if is_abstention(answer):
        return 1.0
    words = [w for w in normalize_answer(answer).split() if w not in _STOPWORDS and len(w) > 1]
    if not words:
        return 1.0
    support = set(normalize_answer(" ".join(context)).split())
    return sum(w in support for w in words) / len(words)


def retrieval_rate(evidence: Sequence[int]) -> float:
    """1 if the answer was made from passages, 0 if the system answered without retrieving. For a
    gated system the mean is how often the gate let retrieval through: the efficiency side of an
    adaptive-retrieval result (report it next to accuracy)."""
    return float(bool(evidence))


# --- retrieval metrics -----------------------------------------------------------------------


def recall_at_k(ranking: Sequence[int], relevant: Sequence[int], k: int) -> float:
    """Share of the relevant passages found in the top k."""
    if not relevant:
        return 0.0
    return len(set(ranking[:k]) & set(relevant)) / len(set(relevant))


def precision_at_k(ranking: Sequence[int], relevant: Sequence[int], k: int) -> float:
    return len(set(ranking[:k]) & set(relevant)) / k


def hit_at_k(ranking: Sequence[int], relevant: Sequence[int], k: int) -> float:
    """1 if any relevant passage is in the top k ("top-k retrieval accuracy")."""
    return float(bool(set(ranking[:k]) & set(relevant)))


def mrr(ranking: Sequence[int], relevant: Sequence[int]) -> float:
    """Reciprocal rank of the first relevant passage (0 if none is ranked)."""
    for rank, passage in enumerate(ranking, start=1):
        if passage in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranking: Sequence[int], relevant: Sequence[int], k: int) -> float:
    """Binary-gain nDCG: DCG of the ranking over the DCG of an ideal ranking."""
    wanted = set(relevant)
    dcg = sum(1 / math.log2(rank + 1) for rank, p in enumerate(ranking[:k], start=1) if p in wanted)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(wanted), k) + 1))
    return dcg / ideal if ideal else 0.0


# --- names from the plan ---------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    label: str  # "recall@5"
    family: str  # "answer" | "retrieval"
    compute: Callable[..., float]


_ANSWER = {
    "accuracy": accuracy,
    "exact match": exact_match,
    "em": exact_match,
    "f1": token_f1,
    "contains": contains,
    "answer contains": contains,
    "abstention": abstention,
    "abstention rate": abstention,
}
_AT_K = {
    "recall": recall_at_k,
    "precision": precision_at_k,
    "hit rate": hit_at_k,
    "top-k retrieval accuracy": hit_at_k,
    "top-k accuracy": hit_at_k,
    "ndcg": ndcg_at_k,
}
_AT_K_LABEL = {"top-k retrieval accuracy": "hit", "top-k accuracy": "hit", "hit rate": "hit"}


_FAITHFULNESS_NAMES = {
    "faithfulness",
    "hallucination",
    "hallucination rate",
    "factuality",
    "factual consistency",
    "attribution",
}


def expand_metric(name: str, ks: Sequence[int] = DEFAULT_KS) -> list[Metric]:
    """ "Recall@k" → recall@1, recall@5, recall@10; "Exact match" → exact_match; …"""
    key = " ".join(name.lower().replace("_", " ").split())
    if key in _ANSWER:
        label = {
            "em": "exact_match",
            "exact match": "exact_match",
            "answer contains": "contains",
            "abstention rate": "abstention",
        }.get(key, key)
        return [Metric(label, "answer", _ANSWER[key])]
    if key == "mrr":
        return [Metric("mrr", "retrieval", mrr)]
    if key in ("groundedness", "grounded"):
        return [Metric("groundedness", "grounded", groundedness)]
    if key in ("retrieval rate", "retrieval frequency", "retrieval ratio"):
        return [Metric("retrieval_rate", "evidence", retrieval_rate)]
    match = re.fullmatch(r"(.+?)(?:\s*@\s*(k|\d+))?", key)
    if match and match.group(1) in _AT_K:
        base, fixed = match.group(1), match.group(2)
        if base.startswith("top-k"):  # the "k" is in the name itself
            fixed = fixed or "k"
        function = _AT_K[base]
        label = _AT_K_LABEL.get(base, base)
        values = [int(fixed)] if fixed and fixed != "k" else list(ks)
        return [
            Metric(f"{label}@{k}", "retrieval", lambda r, rel, k=k, f=function: f(r, rel, k))
            for k in values
        ]
    if key in _FAITHFULNESS_NAMES:
        raise UnknownMetric(
            f"“{name}” is not implemented: measuring it needs an entailment model or a judge. "
            "`groundedness` is a cheap lexical proxy you can use meanwhile (it is not the same thing)."
        )
    raise UnknownMetric(f"No implementation for the metric “{name}”. Add one to metrics.py.")

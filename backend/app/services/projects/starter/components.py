"""Retrieval building blocks: real, small, checkable implementations of what papers in this area
build on, so a first runnable version of a system exists before any research code is written.

    scorers    BM25 (standard library) · dense bi-encoders: DPR, Contriever, a sentence-transformer
               · a cross-encoder reranker
    fusion     reciprocal rank fusion
    Pipeline   first-stage scorer(s) → fusion → optional rerank of the top candidates
    reader     an extractive reader (the best sentence of the top passage); answers written by a
               language model are in generation.py

The dense scorers and the reranker use *public pretrained checkpoints* (nothing is trained or
fine-tuned here) and need `pip install sentence-transformers` (which brings transformers and
torch); the first use downloads the model. BM25 needs nothing.

A scorer has `score(example) -> list[float]`, one score per passage of the example, higher is
better, and optionally `prepare(examples)` to see the whole dataset once (BM25 learns its word
statistics there).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, NamedTuple, Protocol

Example = dict[str, Any]

MODELS = {
    "dpr_question": "facebook/dpr-question_encoder-single-nq-base",
    "dpr_context": "facebook/dpr-ctx_encoder-single-nq-base",
    "contriever": "facebook/contriever",
    "sentence": "BAAI/bge-small-en-v1.5",
    "cross_encoder": "cross-encoder/ms-marco-MiniLM-L-6-v2",
}
RERANK_DEPTH = 20
RRF_K = 60

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
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
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class Scorer(Protocol):
    def score(self, example: Example) -> list[float]: ...


# --- BM25 ------------------------------------------------------------------------------------


class BM25Scorer:
    """Okapi BM25 with Lucene's IDF, k1=1.2, b=0.75. Word statistics come from every passage of the
    dataset (`prepare`); without it, from the example's own passages."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._df: Counter[str] = Counter()
        self._docs = 0
        self._avg_len = 0.0

    def prepare(self, examples: Sequence[Example]) -> None:
        passages = {p for ex in examples for p in ex["passages"]}
        self._fit(list(passages))

    def _fit(self, passages: Sequence[str]) -> None:
        tokens = [tokenize(p) for p in passages]
        self._df = Counter(t for doc in tokens for t in set(doc))
        self._docs = len(tokens)
        self._avg_len = sum(len(d) for d in tokens) / len(tokens) if tokens else 0.0

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self._docs - df + 0.5) / (df + 0.5))

    def score(self, example: Example) -> list[float]:
        if not self._docs:
            self._fit(example["passages"])
        query = tokenize(example["question"])
        scores = []
        for passage in example["passages"]:
            tokens = tokenize(passage)
            counts = Counter(tokens)
            norm = 1 - self.b + self.b * len(tokens) / (self._avg_len or 1.0)
            scores.append(
                sum(
                    self._idf(t) * counts[t] * (self.k1 + 1) / (counts[t] + self.k1 * norm)
                    for t in set(query)
                    if counts[t]
                )
            )
        return scores


# --- dense bi-encoders and the reranker (pretrained checkpoints, lazy) -------------------------


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


@lru_cache(maxsize=4)
def _sentence_model(model_id: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id)


@lru_cache(maxsize=4)
def _cross_encoder(model_id: str) -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_id)


@lru_cache(maxsize=4)
def _transformer(model_id: str, kind: str) -> tuple[Any, Any]:
    from transformers import AutoModel, AutoTokenizer, DPRContextEncoder, DPRQuestionEncoder

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if kind == "dpr_question":
        model = DPRQuestionEncoder.from_pretrained(model_id)
    elif kind == "dpr_context":
        model = DPRContextEncoder.from_pretrained(model_id)
    else:
        model = AutoModel.from_pretrained(model_id)
    return tokenizer, model.eval()


class _Embedder:
    """Passage vectors are computed once per distinct text and kept."""

    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def embed_passages(self, passages: Sequence[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(p for p in passages if p not in self._cache))
        if missing:
            for text, vector in zip(missing, self.encode_passages(missing), strict=True):
                self._cache[text] = vector
        return [self._cache[p] for p in passages]

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def encode_question(self, text: str) -> list[float]:
        raise NotImplementedError

    def score(self, example: Example) -> list[float]:
        question = self.encode_question(example["question"])
        return [_dot(question, p) for p in self.embed_passages(example["passages"])]


class SentenceScorer(_Embedder):
    """A sentence-transformers bi-encoder (default BAAI/bge-small-en-v1.5), cosine similarity.
    BGE models want an instruction in front of *questions*; it is added here."""

    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_id: str = MODELS["sentence"]) -> None:
        super().__init__()
        self.model_id = model_id

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        vectors = _sentence_model(self.model_id).encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]

    def encode_question(self, text: str) -> list[float]:
        prefix = self.QUERY_PREFIX if "bge" in self.model_id.lower() else ""
        vector = _sentence_model(self.model_id).encode([prefix + text], normalize_embeddings=True)[
            0
        ]
        return list(map(float, vector))


class ContrieverScorer(_Embedder):
    """Contriever (facebook/contriever): mean pooling over the token vectors, dot product, as in
    the model card. The public checkpoint is unsupervised-pretrained, not fine-tuned."""

    def __init__(self, model_id: str = MODELS["contriever"]) -> None:
        super().__init__()
        self.model_id = model_id

    def _encode(self, texts: list[str]) -> list[list[float]]:
        import torch

        tokenizer, model = _transformer(self.model_id, "contriever")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 16):
            batch = tokenizer(
                texts[start : start + 16],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            with torch.no_grad():
                hidden = model(**batch)[0]
            mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
            vectors += [list(map(float, row)) for row in pooled]
        return vectors

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def encode_question(self, text: str) -> list[float]:
        return self._encode([text])[0]


class DPRScorer(_Embedder):
    """DPR with the public NQ checkpoints (separate question and passage encoders; the pooled
    [CLS] vector; dot product)."""

    def __init__(
        self,
        question_model: str = MODELS["dpr_question"],
        context_model: str = MODELS["dpr_context"],
    ) -> None:
        super().__init__()
        self.question_model, self.context_model = question_model, context_model

    def _encode(self, model_id: str, kind: str, texts: list[str]) -> list[list[float]]:
        import torch

        tokenizer, model = _transformer(model_id, kind)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 16):
            batch = tokenizer(
                texts[start : start + 16],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            with torch.no_grad():
                pooled = model(**batch).pooler_output
            vectors += [list(map(float, row)) for row in pooled]
        return vectors

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(self.context_model, "dpr_context", texts)

    def encode_question(self, text: str) -> list[float]:
        return self._encode(self.question_model, "dpr_question", [text])[0]


class CrossEncoderScorer:
    """A cross-encoder (default cross-encoder/ms-marco-MiniLM-L-6-v2) scoring each (question,
    passage) pair together. Slower than a bi-encoder, so used on the top candidates only."""

    def __init__(self, model_id: str = MODELS["cross_encoder"]) -> None:
        self.model_id = model_id

    def score(self, example: Example) -> list[float]:
        if not example["passages"]:
            return []
        pairs = [(example["question"], p) for p in example["passages"]]
        return [float(s) for s in _cross_encoder(self.model_id).predict(pairs)]


# --- fusion and the pipeline ------------------------------------------------------------------


def order_of(scores: Sequence[float]) -> list[int]:
    """Indices best first; ties keep the original order."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def z_top(scores: Sequence[float]) -> float:
    """The best score in standard deviations above the mean (population standard deviation)."""
    mean = sum(scores) / len(scores)
    spread = math.sqrt(sum((x - mean) ** 2 for x in scores) / len(scores))
    return (max(scores) - mean) / spread if spread > 0 else 0.0


def rrf(score_lists: Sequence[Sequence[float]], k: int = RRF_K) -> list[float]:
    """Reciprocal rank fusion: each list contributes 1 / (k + rank) to every passage."""
    fused = [0.0] * len(score_lists[0])
    for scores in score_lists:
        for rank, index in enumerate(order_of(scores), start=1):
            fused[index] += 1.0 / (k + rank)
    return fused


class Pipeline:
    """First-stage scorer(s), fused by RRF when there are several, then an optional rerank of the
    top `depth` candidates; whatever is below the depth keeps its first-stage order."""

    def __init__(
        self,
        first_stage: Sequence[Scorer],
        reranker: Scorer | None = None,
        depth: int = RERANK_DEPTH,
    ) -> None:
        if not first_stage:
            raise ValueError("A pipeline needs at least one first-stage scorer.")
        self.first_stage, self.reranker, self.depth = list(first_stage), reranker, depth
        self._scored: tuple[Any, list[list[float]]] = (None, [])

    def prepare(self, examples: Sequence[Example]) -> None:
        for scorer in self.first_stage:
            if hasattr(scorer, "prepare"):
                scorer.prepare(examples)

    def first_stage_scores(self, example: Example) -> list[list[float]]:
        """One score list per first-stage scorer (kept for the last example: rank() and
        confidence() both need them)."""
        if self._scored[0] is not example:
            self._scored = (example, [s.score(example) for s in self.first_stage])
        return self._scored[1]

    def confidence(self, example: Example) -> float:
        """How clearly the best candidate stands out: its first-stage score in standard
        deviations above the mean of all candidates (a z-score), averaged over the first-stage
        scorers. Scale-free, so the same threshold means the same thing for BM25 and a dense
        model. Flat scores give 0. With fewer than two candidates there is nothing to compare:
        infinity (a gate then retrieves). It measures how much the best candidate stands out, not
        how good it is: one weak match among passages sharing no word with the question stands
        out as much as one strong match. Swap in your own signal here if that matters for you."""
        if len(example["passages"]) < 2:
            return math.inf
        return sum(z_top(scores) for scores in self.first_stage_scores(example)) / len(
            self.first_stage
        )

    def rank(self, example: Example) -> list[int]:
        if not example["passages"]:
            return []
        lists = self.first_stage_scores(example)
        order = order_of(lists[0] if len(lists) == 1 else rrf(lists))
        if self.reranker is None:
            return order
        top, rest = order[: self.depth], order[self.depth :]
        subset = {
            "question": example["question"],
            "passages": [example["passages"][i] for i in top],
        }
        reranked = [top[i] for i in order_of(self.reranker.score(subset))]
        return reranked + rest


# --- names from a plan ------------------------------------------------------------------------

STAGES = {
    "bm25": ("BM25", lambda: BM25Scorer()),
    "dpr": ("DPR (public NQ checkpoints)", lambda: DPRScorer()),
    "contriever": ("Contriever (public pretrained checkpoint)", lambda: ContrieverScorer()),
    "sentence": ("BGE-small sentence-transformer", lambda: SentenceScorer()),
}
# What a name in the plan means here. Anything not listed has no implementation in this file.
ALIASES = {
    "bm25": ["bm25"],
    "dpr": ["dpr"],
    "densepassageretrieval": ["dpr"],
    "contriever": ["contriever"],
    "contrastivelearning": ["contriever"],
    "denseretrieval": ["sentence"],
    "sentencebert": ["sentence"],
    "sbert": ["sentence"],
    "hybridretrieval": ["bm25", "sentence"],
    "hybridsearch": ["bm25", "sentence"],
}
RERANK_NAMES = {"reranking", "rerank", "reranker", "crossencoder", "crossencoderreranking"}
# Generation: a language model writes the answer from the top passages (generation.py).
GENERATE_NAMES = {
    "rag",
    "retrievalaugmentedgeneration",
    "retrievalaugmentedgenerationrag",
    "standardrag",
    "vanillarag",
    "naiverag",
    "answergeneration",
    "generation",
}
# Retrieval decided per question, without labels: generation behind a gate (config.json "gate").
# Named systems that *train* a decision (Self-RAG, Adaptive-RAG) are not this and stay unmapped.
GATE_NAMES = {
    "adaptiveretrieval",
    "selectiveretrieval",
    "conditionalretrieval",
    "gatedretrieval",
    "retrievalgate",
    "retrievalgating",
    "retrieveonlywhenneeded",
    "retrievalondemand",
    "ondemandretrieval",
}
# A language model answering from the question alone: the usual "no retrieval" baseline.
CLOSED_BOOK_NAMES = {
    "closedbook",
    "closedbookqa",
    "closedbookllm",
    "noretrieval",
    "llmwithoutretrieval",
    "llmonly",
}


class Plan(NamedTuple):
    stages: list[str]  # first-stage scorers; empty with `generate` = closed-book
    rerank: bool
    generate: bool  # answers come from a language model, not the extractive reader
    gate: bool  # the model decides per question whether to retrieve (implies generate)
    unmapped: list[str]  # names in the plan with no implementation here


def compact(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def resolve(names: Sequence[str]) -> Plan:
    """Plan names → which components to assemble, and what is left unimplemented."""
    stages: list[str] = []
    rerank = generate = gate = closed_book = False
    unmapped: list[str] = []
    for name in names:
        key = compact(name)
        if key in RERANK_NAMES:
            rerank = True
        elif key in GENERATE_NAMES:
            generate = True
        elif key in GATE_NAMES:
            generate = gate = True
        elif key in CLOSED_BOOK_NAMES:
            generate = closed_book = True
        elif key in ALIASES:
            stages += [s for s in ALIASES[key] if s not in stages]
        else:
            unmapped.append(name)
    if gate:
        closed_book = False  # a gate chooses between closed-book and retrieval per question
    if not stages and (rerank or (generate and not closed_book)):
        stages = ["bm25"]  # a reranker needs candidates; so does retrieval-augmented generation
    return Plan(stages, rerank, generate, gate, unmapped)


def describe(
    stages: Sequence[str], rerank: bool, generate: bool = False, gate: bool = False
) -> str:
    if not stages:
        return "no retrieval: a language model answers from the question alone (closed-book)"
    parts = [STAGES[s][0] for s in stages]
    text = " + ".join(parts) + (" fused by reciprocal rank fusion" if len(parts) > 1 else "")
    text += f", top {RERANK_DEPTH} reranked by a cross-encoder" if rerank else ""
    if gate:
        return text + "; a language model answers, retrieving only when a gate says so"
    return text + ("; a language model answers from the top passages" if generate else "")


def build(stages: Sequence[str], rerank: bool) -> Pipeline:
    return Pipeline([STAGES[s][1]() for s in stages], CrossEncoderScorer() if rerank else None)


# --- a simple extractive reader ---------------------------------------------------------------


def best_sentence(question: str, passage: str) -> str:
    """The sentence of the passage sharing most words with the question. Not a language model:
    an answer is only ever text that is in the passage."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", passage) if s.strip()] or [passage]
    words = set(tokenize(question))
    return max(sentences, key=lambda s: len(words & set(tokenize(s))))

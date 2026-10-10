"""Claim verification: is each statement actually backed by the passages it cites?

The answer is split into claims (sentences/list items). Each claim is checked
against its cited passages:

- `nli`: a natural-language-inference cross-encoder scores whether the passage
  *entails* the claim (premise = passage, hypothesis = claim). This is the
  defensible signal; it runs locally and is small (DeBERTa-v3-xsmall).
- `lexical`: fraction of the claim's content terms found in the cited passages
  (fallback when no NLI model is available; also used in tests).

Per claim: supported / partial / unsupported (or uncited). The answer's overall
status is derived from the claims — a count anyone can check — instead of a
made-up "93% confidence".
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.models.manager import ModelManager, resolve_device
from app.services.rag.citations import Claim

SUPPORTED, PARTIAL, UNSUPPORTED, UNCITED = "supported", "partial", "unsupported", "uncited"


class Verifier(Protocol):
    name: str

    def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        """(premise, hypothesis) → (P(entailment), P(contradiction))."""
        ...


class LexicalVerifier:
    name = "lexical-coverage-v1"

    def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        from app.services.retrieval.text import analyze

        scores = []
        for premise, hypothesis in pairs:
            claim_terms = set(analyze(hypothesis))
            if not claim_terms:
                scores.append((0.0, 0.0))
                continue
            coverage = len(claim_terms & set(analyze(premise))) / len(claim_terms)
            # Some shared vocabulary is expected even for unrelated claims; only coverage
            # above 30% counts, scaled so ~65% coverage reaches the 'supported' threshold.
            scores.append((max(0.0, (coverage - 0.3) / 0.7), 0.0))
        return scores


class NLIVerifier:
    def __init__(self, model_name: str, manager: ModelManager, device: str = "auto") -> None:
        self.name = model_name
        self.manager = manager
        self.device = resolve_device(device)

    def _model(self) -> Any:
        def load() -> Any:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(self.name, device=self.device, max_length=512)

        return self.manager.get(f"nli:{self.name}:{self.device}", load)

    def entailment(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        if not pairs:
            return []
        import torch

        model = self._model()
        logits = model.predict(
            pairs, activation_fn=torch.nn.Identity(), convert_to_numpy=True, show_progress_bar=False
        )
        probabilities = torch.softmax(torch.as_tensor(logits), dim=-1).numpy()
        labels = {v.lower(): int(k) for k, v in model.model.config.id2label.items()}
        entail, contradict = labels["entailment"], labels["contradiction"]
        return [(float(p[entail]), float(p[contradict])) for p in probabilities]


@dataclass
class ClaimResult:
    text: str
    citations: list[int]
    status: str  # judged against the passages the claim cites (uncited: it cites none)
    entailment: float
    best_passage: int | None
    # A passage that supports the claim when its own citations don't (missing or wrong
    # citation): "supported by [3], but not cited" / "supported by [3], but cites [2]".
    found_in: int | None = None


@dataclass
class Verification:
    status: str  # supported | partial | unsupported | insufficient | unverified
    label: str
    explanation: str
    claims: list[ClaimResult]
    verifier: str


def classify(entailment: float, contradiction: float) -> str:
    if entailment >= 0.5:
        return SUPPORTED
    if contradiction >= 0.6:
        return UNSUPPORTED
    if entailment >= 0.2:
        return PARTIAL
    return UNSUPPORTED


# Passages are checked in overlapping windows: cross-encoders truncate long inputs, and the
# small NLI model also loses accuracy on long premises. Measured on real answers: a claim copied
# almost verbatim from a 180-word passage scored 0.05 with 120-word windows, 0.99 with 60.
WINDOW_WORDS = 60
WINDOW_STRIDE = 30
# "First, …" / "Moreover, …" are discourse glue, not part of the claim being checked.
_OPENER = re.compile(
    r"^(first|second|third|fourth|finally|also|in addition|moreover|additionally|furthermore),\s*",
    re.I,
)


def _claim_text(text: str) -> str:
    stripped = _OPENER.sub("", text)
    return stripped[:1].upper() + stripped[1:] if stripped else text


def passage_windows(text: str) -> list[str]:
    """Overlapping sentence-aligned windows, so evidence late in a long passage is still seen."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s]
    windows: list[str] = []
    start = 0
    while start < len(sentences):
        words, end = 0, start
        while end < len(sentences) and (words < WINDOW_WORDS or end == start):
            words += len(sentences[end].split())
            end += 1
        windows.append(" ".join(sentences[start:end]))
        if end >= len(sentences):
            break
        # next window starts about WINDOW_STRIDE words later (always moves forward)
        advanced, step = 0, start
        while step < end - 1 and advanced < WINDOW_STRIDE:
            advanced += len(sentences[step].split())
            step += 1
        start = max(step, start + 1)
    return windows or [text]


def sentence_windows(text: str) -> list[str]:
    """Single sentences and adjacent pairs: the narrow premises for a second look."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s]
    pairs = [f"{a} {b}" for a, b in itertools.pairwise(sentences)]
    return sentences + pairs


def _best_scores(
    verifier: Verifier,
    requests: list[tuple[int, str, list[int]]],
    windows: dict[int, list[str]],
) -> dict[int, tuple[float, float, int]]:
    """For each (claim index, claim text, passage numbers): best (entail, contradict, passage)."""
    pairs: list[tuple[str, str]] = []
    owners: list[tuple[int, int]] = []
    for index, text, numbers in requests:
        for number in numbers:
            for window in windows[number]:
                pairs.append((window, _claim_text(text)))
                owners.append((index, number))
    best: dict[int, tuple[float, float, int]] = {}
    for (index, number), (entail, contradict) in zip(
        owners, verifier.entailment(pairs), strict=True
    ):
        current = best.get(index)
        if current is None or entail > current[0]:
            best[index] = (entail, contradict, number)
    return best


def verify_claims(
    verifier: Verifier,
    claims: list[Claim],
    passages: dict[int, str],
    context: str | dict[int, str] | None = None,
) -> list[ClaimResult]:
    """Check each claim against the passages it cites (best window wins).

    When a claim cites nothing, or its citations don't support it, the other passages are
    checked too, so the result can say "supported by [3], but cites [2]" (a wrong citation,
    seen with small models citing a figure caption) instead of only "not supported".

    `context` (e.g. the paper's title; per passage when they come from several papers) is
    put before every window: a passage saying "we
    learn an update B A" only entails "Low-rank adapters learn …" if the model knows which
    paper "we" is (measured: 0.00 without the title, 0.82 with it).
    """

    def prefix(number: int) -> str | None:
        return context.get(number) if isinstance(context, dict) else context

    windows = {
        number: [f"{prefix(number)}. {w}" if prefix(number) else w for w in passage_windows(text)]
        for number, text in passages.items()
    }
    cited = {i: [n for n in c.citations if n in passages] for i, c in enumerate(claims)}
    first = _best_scores(
        verifier, [(i, c.text, cited[i]) for i, c in enumerate(claims) if cited[i]], windows
    )
    # Second look at the cited passages, sentence by sentence: the small NLI model can miss a
    # long claim inside a multi-sentence window (measured: a claim copied verbatim from a
    # passage scored 0.19 in its 60-word window and 0.99 against its own sentence).
    narrow = {
        number: [f"{prefix(number)}. {w}" if prefix(number) else w for w in sentence_windows(text)]
        for number, text in passages.items()
    }
    second = _best_scores(
        verifier,
        [
            (i, c.text, cited[i])
            for i, c in enumerate(claims)
            if i in first and classify(*first[i][:2]) != SUPPORTED
        ],
        narrow,
    )
    for i, score in second.items():
        if score[0] > first[i][0]:
            first[i] = score
    retry = [
        (i, c.text, [n for n in passages if n not in cited[i]])
        for i, c in enumerate(claims)
        if (i not in first or classify(*first[i][:2]) != SUPPORTED)
        and len(cited[i]) < len(passages)
    ]
    elsewhere = _best_scores(verifier, retry, windows)

    results = []
    for index, claim in enumerate(claims):
        other = elsewhere.get(index)
        found_in = other[2] if other and classify(*other[:2]) == SUPPORTED else None
        if index in first:
            entail, contradict, number = first[index]
            status = classify(entail, contradict)
        else:
            entail, status, number = (other[0] if other else 0.0), UNCITED, None
        results.append(
            ClaimResult(
                claim.text,
                claim.citations,
                status,
                round(entail, 3),
                number if found_in is None else found_in,
                found_in=found_in,
            )
        )
    return results


def summarize(claims: list[ClaimResult], verifier: str, insufficient: bool) -> Verification:
    if insufficient:
        return Verification(
            "insufficient",
            "Insufficient evidence",
            "The indexed papers don't contain enough evidence to answer this.",
            claims,
            verifier,
        )
    total = len(claims)
    missing = sum(c.found_in is not None and not c.citations for c in claims)
    wrong = sum(c.found_in is not None and bool(c.citations) for c in claims)
    # Backed by the evidence counts as supported; citation problems are reported separately.
    supported = sum(c.status == SUPPORTED or c.found_in is not None for c in claims)
    partial = sum(c.status == PARTIAL and c.found_in is None for c in claims)
    weak = total - supported - partial
    if total == 0:
        return Verification("unverified", "Not verified", "No checkable statements.", [], verifier)
    parts = [f"{supported} of {total} statement{'s' if total != 1 else ''} directly supported"]
    if partial:
        parts.append(f"{partial} partially supported")
    if weak:
        parts.append(f"{weak} not supported by the passages")
    if missing:
        parts.append(f"{missing} supported but missing a citation")
    if wrong:
        parts.append(f"{wrong} supported by a different passage than the one cited")
    explanation = "; ".join(parts) + "."
    if supported == total or (supported >= 0.8 * total and weak == 0):
        return Verification("supported", "Well supported", explanation, claims, verifier)
    if supported + partial >= total / 2:
        return Verification("partial", "Partially supported", explanation, claims, verifier)
    return Verification("unsupported", "Insufficient evidence", explanation, claims, verifier)

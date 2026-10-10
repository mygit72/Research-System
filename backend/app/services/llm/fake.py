"""Deterministic offline "LLM" for tests and demos — NOT a language model.

It reads the numbered evidence blocks from the prompt (the same format the RAG
pipeline sends to real models), picks the sentences that share the most terms
with the question, and answers with them, citing their block numbers. That makes
the whole pipeline (streaming, citation parsing, verification) testable without
a model, and its answers are always grounded by construction.

Summary prompts ("Fields:" with "LABEL: question" lines) are answered the same
way, one labelled line per field, or "Not reported." when nothing matches.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.services.llm.base import GenerationParams, Message, StreamEvent, Usage, count_tokens

_BLOCK = re.compile(r"^\[(\d+)\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", re.S | re.M)
_PASSAGE = re.compile(r"^\[(\d+)\] ([^\n]*)\n(.*?)(?=^\[\d+\]|\Z)", re.S | re.M)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
INSUFFICIENT = "I couldn't find sufficient evidence in the indexed papers."
_CELL = re.compile(r"Paper [A-Z]: (.*?)(?= [|] Paper [A-Z]: |$)")
FIELDS_MARKER = "\nFields:\n"
# Words a real model would associate with each summary field (a lexical stand-in).
_FIELD_HINTS = {
    "PROBLEM": "expensive costly challenge difficult requires",
    "MOTIVATION": "important matters billions clusters cost",
    "CONTRIBUTION": "we propose introduce study focus present",
    "METHOD": "learn update approach freeze",
    "ARCHITECTURE": "matrix matrices layer transformer rank",
    "DATASET": "datasets data corpus",
    "EXPERIMENTS": "evaluate compare experiments",
    "RESULTS": "within improvement results percent outperforms",
    "LIMITATIONS": "only limited may differ",
    "FUTURE_WORK": "future",
    "MODEL": "model adapters propose",
    "TRAINING": "train gradients receive",
    "EVALUATION": "evaluate compare baseline",
    "METRICS": "accuracy recall score metric",
    "COMPUTE": "gpu memory parameters billion",
    "TRAINING_DATA": "text data corpus",
    "PREPROCESSING": "tokenize preprocess clean",
    "OBJECTIVE": "objective learn update",
    "LOSS": "loss function",
    "OPTIMIZATION": "learning rate optimizer scaled",
    "HYPERPARAMETERS": "rank alpha batch",
    "EVALUATION_METHOD": "evaluate datasets",
}


class FakeLLM:
    name = "fake"
    model_id = "fake-extractive-v1"
    is_remote = False

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def answer(self, prompt: str) -> str:
        from app.services.retrieval.text import analyze

        if FIELDS_MARKER in prompt:
            return self.fill_fields(prompt)
        if "What research topic do these papers share?" in prompt:  # topic naming
            terms = re.search(r"^Key terms: (.*)$", prompt, re.M)
            words = [t.strip() for t in (terms.group(1) if terms else "").split(",") if t.strip()]
            return " and ".join(words[:2]).capitalize() or "Other"
        if "You write evaluation questions" in prompt:  # question generation: from the passage
            passage = prompt.rsplit("Passage:", 1)[-1]
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", passage)][:6]
            return f"What does the paper report about {' '.join(words).lower()}?"
        question = prompt.rsplit("Question:", 1)[-1]
        terms = set(analyze(question))
        evidence = prompt.split("Evidence:", 1)[-1].split("Question:", 1)[0]
        scored: list[tuple[int, int, str]] = []
        for number, body in _BLOCK.findall(evidence):
            for sentence in _SENTENCE.split(" ".join(body.split())):
                overlap = len(terms & set(analyze(sentence)))
                if overlap and len(sentence) > 20:
                    scored.append((overlap, int(number), sentence.rstrip(".")))
        if not scored:
            return INSUFFICIENT
        best = sorted(scored, key=lambda s: (-s[0], s[1]))[:2]
        return " ".join(f"{sentence} [{number}]." for _, number, sentence in best)

    def fill_fields(self, prompt: str) -> str:
        """Each "LABEL: question" line gets the best matching sentence not used yet."""
        from app.services.retrieval.text import analyze

        body, fields = prompt.rsplit(FIELDS_MARKER, 1)
        fields = fields.split("Answer format", 1)[0]  # the template repeats the labels
        labels = [line.partition(":")[0].strip() for line in fields.strip().splitlines()]
        if "Comparison table" in body:  # overview: the first row two papers both report
            for line in body.split("Comparison table", 1)[1].splitlines():
                cells = _CELL.findall(line)
                reported = [c for c in cells if c and not c.startswith("Not reported")]
                if len(reported) >= 2:
                    return f"{labels[0]}: Paper A: {reported[0]} Paper B: {reported[1]}"
            return f"{labels[0]}: Not reported."
        if "Summary so far" in body:  # takeaway: repeat the key contribution
            notes = [n for n in body.splitlines() if re.match(r"[A-Z_]+: ", n)]
            chosen = next((n for n in notes if n.startswith("CONTRIBUTION:")), None)
            chosen = chosen or (notes[0] if notes else None)
            text = chosen.split(":", 1)[1].strip() if chosen else "Not reported."
            return f"{labels[0]}: {text}"
        sentences: list[tuple[int, set[str], str]] = []
        for number, heading, text in _PASSAGE.findall(body.split("Passages:", 1)[-1]):
            for sentence in _SENTENCE.split(" ".join(text.split())):
                if len(sentence) > 20:
                    terms = set(analyze(f"{heading} {sentence}"))
                    sentences.append((int(number), terms, sentence.rstrip(".")))
        lines: list[str] = []
        used: set[str] = set()
        for line in fields.strip().splitlines():
            label, _, question = line.partition(":")
            hints = _FIELD_HINTS.get(label.strip(), "")
            terms = set(analyze(f"{label.replace('_', ' ')} {question} {hints}"))
            scored = [
                (len(terms & sentence_terms), -i, number, sentence)
                for i, (number, sentence_terms, sentence) in enumerate(sentences)
                if sentence not in used
            ]
            best = max(scored, default=None)
            if best is None or best[0] == 0:
                lines.append(f"{label}: Not reported.")
                continue
            used.add(best[3])
            lines.append(f"{label}: {best[3]} [{best[2]}].")
        return "\n".join(lines)

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        prompt = "\n".join(m.content for m in messages)
        text = self.answer(prompt)
        for word in re.findall(r"\S+\s*", text):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield StreamEvent(text=word)
        yield StreamEvent(
            done=True,
            usage=Usage(count_tokens(prompt), count_tokens(text)),
            stop_reason="end_turn",
            model=self.model_id,
        )

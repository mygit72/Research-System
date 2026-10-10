"""The field-extraction engine shared by summaries and comparisons.

For a paper and a list of section groups (each a set of fields answered by one
part of the paper):

    choose passages (passages.py) → one model call per group with labelled fields
    → parse → keep only citations to the passages that call was given → normalize
    → check every statement with the NLI verifier (paper title as context)

Passages are numbered once per paper, so every field's citations point into one
`sources` list. A field the passages don't answer is "Not reported.".
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk, Document
from app.services.llm import GenerationParams, LLMProvider, Message, count_tokens
from app.services.rag.citations import Claim, split_claims, validate_citations
from app.services.rag.verify import ClaimResult, Verifier, summarize, verify_claims
from app.services.summaries.passages import Chosen, PaperPassages
from app.services.summaries.prompt import (
    Block,
    group_messages,
    has_label,
    has_text,
    is_not_reported,
    parse_fields,
)
from app.services.summaries.spec import NOT_REPORTED, Field, Group

RAW_REPLY_LIMIT = 4000

# Labels for a summary section (the chat's "Insufficient evidence" reads oddly here).
SECTION_LABELS = {
    "supported": "Well supported",
    "partial": "Partially supported",
    "unsupported": "Not supported by its sources",
    "unverified": "Not verified",
    "not_reported": "Not reported",
}


def _source_item(number: int, chosen: Chosen, document: PaperInfo, group: str) -> dict[str, Any]:
    chunk = chosen.chunk
    return {
        "number": number,
        "chunk_id": str(chunk.id),
        "document": {
            "id": str(document.id),
            "title": document.title,
            "year": document.year,
            "authors_display": document.authors_display,
        },
        "section_title": chunk.section_title,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "char_start": chunk.char_start,
        "boxes": chunk.boxes,
        "quote": chunk.text,
        "score": chosen.score,
        "group": group,
        "reason": chosen.reason,
    }


def _claim_dict(claim: ClaimResult) -> dict[str, Any]:
    return {
        "text": claim.text,
        "citations": claim.citations,
        "status": claim.status,
        "entailment": claim.entailment,
        "best_passage": claim.best_passage,
        "found_in": claim.found_in,
    }


_MARKERS = re.compile(r"\[[\d,\s\-\u2013]+\]")
# "[4] The method …. Only A …" → "The method … [4]. Only A …" (small models often lead with it).
_LEADING_MARKERS = re.compile(
    r"^\s*((?:\[\d+(?:\s*[,\-\u2013]\s*\d+)*\]\s*)+)(.+?)([.!?])(?=\s|$)", re.S
)
# "Researchers should remember that X" → "X": framing that isn't part of the statement.
_FRAMING = re.compile(
    r"^(?:in\s+(?:one|a\s+single)\s+sentence,?\s*)?"
    r"(?:(?:a\s+)?(?:researchers?|readers?|one|you)\s+should\s+(?:remember|note|know|keep in mind)"
    r"\s+(?:is\s+)?that"
    r"|(?:the\s+)?(?:key|main|one-line|most important)\s+(?:takeaway|point)"
    r"\s+is\s+(?:that\s+)?)\s*",
    re.I,
)
_LABEL_MARKER = re.compile(r"\s*\[[A-Z][A-Z_ ]{2,30}\]")
# "[7] [9] [6] [7]" → "[7][9][6]": adjacent markers merged, repeats dropped.
_MARKER_RUN = re.compile(r"(?:\[[\d,\s\-\u2013]+\]\s*){2,}")
# Fragments become sentences the entailment model can judge. Measured on "MedQA, CaseHOLD, ...":
# bare list 0.00; "Dataset: ..." 0.02 to 0.76 (depends on a full stop); "The datasets used
# are ...." 0.81 to 0.95; "The paper uses ...." 0.78 to 0.85.
FRAGMENT_TEMPLATES = {"dataset": "The datasets used are {}.", "architecture": "The paper uses {}."}


# Seen: a comparison overview ending with all 18 passage numbers. Citing more passages than
# this in one place says nothing, so the run is dropped and the sentence is checked as uncited
# (the verifier then reports which passage, if any, supports it).
MAX_CITATIONS_IN_A_RUN = 4


def _merge_markers(match: re.Match[str]) -> str:
    numbers = [n for group in _MARKERS.findall(match[0]) for n in re.findall(r"\d+", group)]
    unique = list(dict.fromkeys(numbers))
    space = " " if match[0][-1:].isspace() else ""
    if len(unique) > MAX_CITATIONS_IN_A_RUN:
        return space
    return "".join(f"[{n}]" for n in unique) + space


# "… respectively [6]. [7] Memory drops …": after a sentence that has its own citation, a
# marker that starts the next sentence belongs to that next sentence.
_INNER_LEADING = re.compile(r"(\][.!?])\s+((?:\[\d+\])+)\s*(?=[A-Z])")
_SENTENCE_STOP = re.compile(r"[.!?](?=\s|$)")
# "… a learning rate of 2e-5 [14]. [14]": the same citation repeated after the full stop.
_TRAILING_REPEAT = re.compile(r"(\[(\d+)\])([.!?])\s*\[\2\]\s*$")


def _move_inner_leading_markers(text: str) -> str:
    while match := _INNER_LEADING.search(text):
        rest = text[match.end() :]
        stop = _SENTENCE_STOP.search(rest)
        end = stop.start() if stop else len(rest.rstrip())
        sentence = rest[:end].rstrip()
        text = f"{text[: match.start()]}{match[1]} {sentence} {match[2]}{rest[end:].lstrip(' ')}"
        if not stop:
            break
    return text


def normalize_text(field: Field, text: str) -> str:
    # "[CONTRIBUTION]": the takeaway citing a field of the draft instead of a passage.
    text = _LABEL_MARKER.sub("", text).strip()
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = _MARKER_RUN.sub(_merge_markers, text)
    text = _LEADING_MARKERS.sub(lambda m: f"{m[2]} {m[1].strip()}{m[3]}", text, count=1)
    text = _move_inner_leading_markers(text)
    text = _TRAILING_REPEAT.sub(r"\1\3", text)
    if field.key == "takeaway":
        stripped = _FRAMING.sub("", text)
        text = stripped[:1].upper() + stripped[1:] if stripped != text else text
    return text.strip()


def checkable_claims(field: Field, text: str) -> list[Claim]:
    """Claims to verify. A field is one short paragraph, so a sentence without a citation is
    covered by the nearest citation in that field (usually one at the end of the paragraph).
    Fragments ("MedQA, CaseHOLD, FiQA") are turned into sentences (FRAGMENT_TEMPLATES)."""
    claims = split_claims(text)
    result = []
    for index, claim in enumerate(claims):
        citations = claim.citations or next(
            (c.citations for c in [*claims[index + 1 :], *reversed(claims[:index])] if c.citations),
            [],
        )
        lowercase_words = sum(1 for word in claim.text.split() if word[:1].islower())
        if lowercase_words >= 2:
            statement = claim.text
        else:
            template = FRAGMENT_TEMPLATES.get(field.key, field.title + ": {}.")
            statement = template.format(claim.text.rstrip("."))
        result.append(Claim(statement, citations))
    return result


def build_section(
    field: Field,
    text: str,
    passages: dict[int, str],
    verifier: Verifier | None,
    context: str | dict[int, str] | None = None,
) -> tuple[dict[str, Any], list[ClaimResult]]:
    """A field's final text (only valid citations) and its claim-level check.

    `context` (the paper's title) is given to the verifier with every passage."""
    base = {"key": field.key, "title": field.title}
    # Validate first: it also expands ranges ("[6-8]" → "[6][7][8]") before markers are merged.
    check = validate_citations(text, 0, allowed=set(passages))
    text = normalize_text(field, check.text)
    if is_not_reported(text) or not re.search(r"[A-Za-z]{3}", _MARKERS.sub("", text)):
        return base | {
            "text": NOT_REPORTED,
            "citations": [],
            "invalid_citations": [],
            "status": "not_reported",
            "label": SECTION_LABELS["not_reported"],
            "explanation": "The passages used for this part of the summary don't cover it.",
            "claims": [],
        }, []
    claims: list[ClaimResult] = []
    if verifier is None:
        status, explanation = "unverified", "Statement checking is turned off."
    else:
        claims = verify_claims(verifier, checkable_claims(field, text), passages, context)
        verification = summarize(claims, verifier.name, insufficient=False)
        status, explanation = verification.status, verification.explanation
    return base | {
        "text": text,
        "citations": check.cited,
        "invalid_citations": check.invalid,
        "status": status,
        "label": SECTION_LABELS.get(status, status),
        "explanation": explanation,
        "claims": [_claim_dict(c) for c in claims],
    }, claims


def overall_support(
    claims: list[ClaimResult], sections: list[dict[str, Any]], verifier: str
) -> dict[str, Any]:
    not_reported = [s["title"] for s in sections if s["status"] == "not_reported"]
    if not claims:
        status, label = "unverified", "Not verified"
        explanation = "No checkable statements."
    else:
        verification = summarize(claims, verifier, insufficient=False)
        status, explanation = verification.status, verification.explanation
        label = {"unsupported": "Weakly supported"}.get(status, verification.label)
    return {
        "status": status,
        "label": label,
        "explanation": explanation,
        "verifier": verifier,
        "statements": len(claims),
        "not_reported": not_reported,
    }


# Small models sometimes loop on citations ("[7] [9] [6] [7] [8] [9] [1] …") until the token
# limit; seen with qwen2.5:3b, where it cost ~40 s. Generation stops once the tail is a run
# of this many markers.
LOOP_MARKERS = 8
_MARKER_LOOP = re.compile(r"(?:\[[\d,\s-]+\]\s*){" + str(LOOP_MARKERS) + r",}$")


@dataclass(slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str | None
    stopped_loop: bool = False


async def complete(
    llm: LLMProvider, messages: list[Message], params: GenerationParams
) -> Completion:
    """Run one generation to the end (or until it starts looping on citations)."""
    parts: list[str] = []
    result = Completion("", 0, 0, None)
    stream = llm.stream(messages, params)
    try:
        async for event in stream:
            if event.text:
                parts.append(event.text)
                if _MARKER_LOOP.search("".join(parts[-3 * LOOP_MARKERS :])):
                    result.stopped_loop = True
                    break
            if event.done:
                result.input_tokens = event.usage.input_tokens
                result.output_tokens = event.usage.output_tokens
                result.model = event.model
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()  # stops the model's generation (closes the HTTP stream)
    result.text = "".join(parts)
    if result.stopped_loop:
        result.input_tokens = sum(count_tokens(m.content) for m in messages)
        result.output_tokens = count_tokens(result.text)
    return result


def first_line(reply: str) -> str:
    """A one-field reply written without its label: use the first non-empty line."""
    for line in reply.splitlines():
        if line.strip():
            return line.strip()
    return ""


@dataclass
class PaperInfo:
    id: uuid.UUID
    title: str
    year: int | None
    authors_display: str


async def load_paper(
    session: AsyncSession, document: Document, version_id: uuid.UUID
) -> tuple[PaperInfo, list[Chunk]]:
    """A paper's identity and its version's passages, detached from the session."""
    chunks = list(
        (await session.execute(select(Chunk).where(Chunk.version_id == version_id))).scalars()
    )
    for chunk in chunks:
        session.expunge(chunk)
    info = PaperInfo(document.id, document.title, document.year, document.authors_display)
    return info, chunks


@dataclass
class FieldExtractor:
    """Writes, cites and checks the fields of one paper, group by group."""

    paper: PaperInfo
    chunks: dataclasses.InitVar[list[Chunk]]
    llm: LLMProvider
    verifier: Verifier | None
    params: GenerationParams
    context_tokens: int
    max_passages: int
    sections: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    sources: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    claims: list[ClaimResult] = dataclasses.field(default_factory=list)
    trace: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    tokens: dict[str, int] = dataclasses.field(default_factory=lambda: {"input": 0, "output": 0})
    model: str | None = None
    numbers: dict[uuid.UUID, int] = dataclasses.field(default_factory=dict)

    def __post_init__(self, chunks: list[Chunk]) -> None:
        self.passages = PaperPassages(chunks)

    @property
    def drafted(self) -> list[tuple[str, str]]:
        """(field key, text) of every field that was answered."""
        return [(s["key"], s["text"]) for s in self.sections if s["status"] != "not_reported"]

    async def generate(self, messages: list[Message], trace_entry: dict[str, Any]) -> str:
        mark = time.perf_counter()
        result = await complete(self.llm, messages, self.params)
        self.tokens["input"] += result.input_tokens
        self.tokens["output"] += result.output_tokens
        self.model = result.model or self.model
        trace_entry["reply"] = result.text[:RAW_REPLY_LIMIT]
        trace_entry["latency_ms"] = round((time.perf_counter() - mark) * 1000, 1)
        if result.stopped_loop:
            trace_entry["note"] = "Stopped early: the model started repeating citations."
        return result.text

    async def check(self, field: Field, text: str, passages: dict[int, str]) -> dict[str, Any]:
        section, claims = await asyncio.to_thread(
            build_section, field, text, passages, self.verifier, self.paper.title
        )
        self.sections.append(section)
        self.claims += claims
        return section

    async def run_group(self, group: Group) -> None:
        chosen = self.passages.select(group, self.context_tokens, self.max_passages)
        for item in chosen:
            if item.chunk.id not in self.numbers:
                self.numbers[item.chunk.id] = len(self.numbers) + 1
                self.sources.append(
                    _source_item(self.numbers[item.chunk.id], item, self.paper, group.name)
                )
        number = {c.chunk.id: self.numbers[c.chunk.id] for c in chosen}
        passages = {number[c.chunk.id]: c.chunk.text for c in chosen}
        entry: dict[str, Any] = {
            "group": group.name,
            "fields": [f.key for f in group.fields],
            "passages": [
                {
                    "number": number[c.chunk.id],
                    "section_title": c.chunk.section_title,
                    "page": c.chunk.page_start,
                    "reason": c.reason,
                    "tokens": c.tokens,
                }
                for c in chosen
            ],
            "tokens": sum(c.tokens for c in chosen),
        }
        if chosen:
            blocks = [
                Block(
                    number[c.chunk.id],
                    f"{c.chunk.section_title or 'Front matter'}, p. {c.chunk.page_start}",
                    c.chunk.text,
                )
                for c in chosen
            ]
            title, year = self.paper.title, self.paper.year
            reply = await self.generate(group_messages(title, year, blocks, group.fields), entry)
            texts = parse_fields(reply, group.fields)
            # A small model sometimes skips a field entirely (seen: FUTURE_WORK missing although
            # the conclusion states it). Ask once more for just those; an explicit
            # "Not reported." is an answer and is kept.
            # Same for a field answered with citations only ("MODEL: [3]").
            missing = tuple(
                f
                for f in group.fields
                if not has_label(reply, f)
                or (not is_not_reported(texts[f.key]) and not has_text(texts[f.key]))
            )
            if missing and len(missing) < len(group.fields):
                retry_trace: dict[str, Any] = {}
                retry = await self.generate(
                    group_messages(title, year, blocks, missing), retry_trace
                )
                texts |= parse_fields(retry, missing)
                entry["retry"] = {"fields": [f.key for f in missing], **retry_trace}
        else:
            texts = {f.key: NOT_REPORTED for f in group.fields}
            entry["note"] = "No passages for this part of the paper; the model wasn't called."
        for field in group.fields:
            await self.check(field, texts[field.key], passages)
        self.trace.append(entry)

    def finish_sources(self) -> None:
        """Mark which sources are cited and how well the statements citing them hold up."""
        for source in self.sources:
            statuses = [
                c["status"]
                for s in self.sections
                for c in s["claims"]
                if source["number"] in c["citations"]
            ]
            source["cited"] = any(source["number"] in s["citations"] for s in self.sections)
            source["support_status"] = next(
                (s for s in ("supported", "partial", "unsupported") if s in statuses), None
            )

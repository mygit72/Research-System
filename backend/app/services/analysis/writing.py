"""Writing report sections from numbered passages — cited, then checked sentence by sentence.

Same contract as the chat and summaries: the model sees numbered passages ([n], one
numbering for the whole report), must cite them, citations to passages it wasn't given are
dropped, and every sentence is checked against what it cites (NLI, with the passage's paper
title as context). The section's label says how well it held up.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.analysis.digests import SourceBook
from app.services.llm import INSUFFICIENT, GenerationParams, LLMProvider, Message
from app.services.rag.citations import split_claims, validate_citations
from app.services.rag.verify import Verifier, classify, verify_claims
from app.services.summaries.engine import complete

PROMPT_VERSION = "report-v1"

WRITER_SYSTEM = f"""You are writing one section of a research report using ONLY the numbered evidence passages from the user's papers.

Rules:
- Write a single paragraph of 3 to 6 sentences in plain academic English.
- End every sentence with the number of the passage that supports it, placed just before the full stop, like this: "<statement from passage 2> [2]." Never start a sentence with a number. Use only numbers that appear in the evidence.
- Say which paper each point comes from (by its title or its method's name).
- Use only the evidence. Do not add outside knowledge, and never invent numbers, results or paper details.
- If the evidence does not cover the request, reply with exactly: "{INSUFFICIENT}\""""

SECTION_LABELS = {
    "supported": "Well supported",
    "partial": "Partially supported",
    "unsupported": "Not supported by its sources",
    "unverified": "Not verified",
    "insufficient": "Not enough evidence",
}


# Seen with qwen2.5:3b: template placeholders copied literally ("<direction> [2] …") and
# citations written in parentheses ("… for deployment (5)", "(5, 6)").
_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z _-]{1,30}>\s*:?\s*")
_PAREN_CITATION = re.compile(r"\((?:passages?\s+)?(\d{1,2}(?:\s*(?:,|and)\s*\d{1,2})*)\)")


def normalize_citations(text: str, count: int) -> str:
    """Placeholders removed; "(5)" / "(5, 6)" → "[5][6]" when they can only be passage numbers
    (1–2 digits within range, so "(2021)" stays a year)."""
    text = _PLACEHOLDER.sub("", text)

    def paren(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        if numbers and all(1 <= n <= count for n in numbers):
            return "".join(f"[{n}]" for n in dict.fromkeys(numbers))
        return match.group(0)

    return _PAREN_CITATION.sub(paren, text)


# "LoRA, as described in [5], injects …" loses its marker when citations move to the end.
_REFERRING = (
    r"(?:as\s+(?:described|shown|discussed|highlighted|reported|noted|demonstrated|"
    r"introduced|proposed|presented)\s+in|according\s+to|see)"
)
_DANGLING_ASIDE = re.compile(rf"\s*,\s*{_REFERRING}\s*,\s*", re.I)  # "LoRA, as described in, …"
_DANGLING_END = re.compile(rf",?\s*\b{_REFERRING}\s*(?=[.;:]|$)", re.I)  # "… as shown in."


def _with_citations(sentence: str, numbers: list[int]) -> str:
    """'A claim.' + [3] → 'A claim [3].'"""
    sentence = _DANGLING_END.sub("", _DANGLING_ASIDE.sub(" ", sentence.strip())).strip()
    end = sentence[-1] if sentence[-1:] in (".", "!", "?") else "."
    body = sentence[:-1].rstrip() if sentence[-1:] in (".", "!", "?") else sentence
    markers = "".join(f"[{n}]" for n in numbers)
    return f"{body} {markers}{end}" if markers else f"{body}{end}"


def evidence_blocks(book: SourceBook, numbers: list[int]) -> str:
    blocks = []
    for n in numbers:
        item = book.items[n - 1]
        document = item["document"]
        year = f" ({document['year']})" if document.get("year") else ""
        blocks.append(
            f"[{n}] {document['title']}{year} — {item.get('section_title') or 'Front matter'}, "
            f"p. {item.get('page_start')}\n{' '.join(str(item['quote']).split())}"
        )
    return "\n\n".join(blocks)


@dataclass
class Writer:
    llm: LLMProvider
    params: GenerationParams
    verifier: Verifier | None
    book: SourceBook
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})
    calls: int = 0
    model: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

    async def generate(self, messages: list[Message], label: str) -> str:
        mark = time.perf_counter()
        result = await complete(self.llm, messages, self.params)
        self.calls += 1
        self.tokens["input"] += result.input_tokens
        self.tokens["output"] += result.output_tokens
        self.model = result.model or self.model
        self.trace.append(
            {
                "step": label,
                "reply": result.text[:3000],
                "latency_ms": round((time.perf_counter() - mark) * 1000, 1),
                "tokens": result.input_tokens + result.output_tokens,
            }
        )
        return result.text

    async def section(
        self,
        key: str,
        title: str,
        instruction: str,
        numbers: list[int],
        system: str = WRITER_SYSTEM,
    ) -> dict[str, Any]:
        """Write and check one section from these passages."""
        numbers = list(dict.fromkeys(numbers))
        if not numbers:
            return _section(key, title, "", [], "insufficient")
        messages = [
            Message("system", system),
            Message(
                "user",
                f"Evidence:\n{evidence_blocks(self.book, numbers)}\n\nQuestion: {instruction}",
            ),
        ]
        reply = await self.generate(messages, key)
        return await self.check(key, title, reply, numbers)

    def _joint_support(
        self, claims: list[Any], results: list[Any], allowed: set[int]
    ) -> dict[int, float]:
        """Sentences citing several passages that no single one supports ("QLoRA quantizes to
        4-bit and uses paged optimizers [1][4]", or a comparison of two papers): check them
        against the cited passages together. Returns {claim index: entailment} for supported."""
        assert self.verifier is not None
        pending = [
            (i, c)
            for i, (c, r) in enumerate(zip(claims, results, strict=True))
            if r.status not in ("supported", "partial")
            and r.found_in is None
            and len([n for n in c.citations if n in allowed]) >= 2
        ]
        if not pending:
            return {}
        scores = self.verifier.entailment(
            [
                (_joint_premise(self.book, [n for n in c.citations if n in allowed]), c.text)
                for _, c in pending
            ]
        )
        return {
            i: round(entail, 3)
            for (i, _), (entail, contradict) in zip(pending, scores, strict=True)
            if classify(entail, contradict) == "supported"
        }

    async def check(self, key: str, title: str, text: str, numbers: list[int]) -> dict[str, Any]:
        allowed = set(numbers)
        # Citations must point to passages this section was given (numbering is report-wide).
        checked = validate_citations(
            normalize_citations(text.strip(), len(self.book.items)), len(self.book.items)
        )
        body = checked.text
        if body.startswith(INSUFFICIENT[:40]):
            return _section(key, title, "", [], "insufficient")
        claims = split_claims(body)
        for claim in claims:
            claim.citations = [n for n in claim.citations if n in allowed]
        cited = sorted({n for c in claims for n in c.citations})
        if self.verifier is None or not claims:
            return _section(key, title, body, cited, "unverified")
        passages = {n: self.book.text(n) for n in numbers}
        context = {n: self.book.title(n) for n in numbers}
        results = await asyncio.to_thread(verify_claims, self.verifier, claims, passages, context)
        # A report is a document people export and reuse, so unlike a chat answer its text
        # keeps only what its passages back up (measured with qwen2.5:3b: 2 of 22 sentences
        # supported as written, many of the rest supported by another passage than the one
        # cited, or not cited at all):
        # - supported / partly supported → kept as cited;
        # - supported by a passage it didn't cite → kept, citation set by the checker;
        # - supported by nothing given → removed, and listed in the section's `removed`.
        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        joint = await asyncio.to_thread(self._joint_support, claims, results, allowed)
        for index, (claim, result) in enumerate(zip(claims, results, strict=True)):
            entry: dict[str, Any] = {
                "text": result.text,
                "citations": [n for n in claim.citations if n in allowed],
                "status": result.status,
                "entailment": result.entailment,
                "found_in": result.found_in,
            }
            if result.status in ("supported", "partial"):
                kept.append(entry)
            elif result.found_in is not None:
                entry["corrected_from"] = entry["citations"]
                entry["citations"] = [result.found_in]
                entry["status"] = "supported"
                entry["entailment"] = None  # the score above was for the passage it cited
                entry["note"] = (
                    "Citation corrected by the checker"
                    if entry["corrected_from"]
                    else "Citation added by the checker"
                )
                kept.append(entry)
            elif index in joint:
                entry["status"] = "supported"
                entry["entailment"] = joint[index]
                entry["note"] = "Supported by the cited passages together"
                kept.append(entry)
            else:
                removed.append(
                    {
                        "text": result.text,
                        "reason": "cites passages that don't support it"
                        if entry["citations"]
                        else "no passage supports it",
                    }
                )
        if not kept:
            section = _section(key, title, "", [], "insufficient")
        else:
            statuses = [c["status"] for c in kept]
            status = "supported" if all(s == "supported" for s in statuses) else "partial"
            text = " ".join(_with_citations(c["text"], c["citations"]) for c in kept)
            section = _section(
                key, title, text, sorted({n for c in kept for n in c["citations"]}), status, kept
            )
        section["removed"] = removed
        return section


JOINT_CHARS = 2400  # what the entailment model can take in one premise


def _joint_premise(book: SourceBook, numbers: list[int]) -> str:
    parts = [f"{book.title(n)}. {' '.join(book.text(n).split())}" for n in numbers]
    share = JOINT_CHARS // max(len(parts), 1)
    return " ".join(part[:share] for part in parts)


def _section(
    key: str,
    title: str,
    text: str,
    citations: list[int],
    status: str,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "kind": "text",
        "text": text,
        "citations": citations,
        "claims": claims or [],
        "status": status,
        "label": SECTION_LABELS.get(status, status),
        "origin": "generated",
    }


def support_summary(sections: list[dict[str, Any]], verifier: str) -> dict[str, Any]:
    claims = [c for s in sections for c in s.get("claims", [])]
    removed = sum(len(s.get("removed", [])) for s in sections)
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim["status"]] = counts.get(claim["status"], 0) + 1
    supported = counts.get("supported", 0)
    corrected = sum(1 for c in claims if c.get("note"))
    total = len(claims)
    if total == 0:
        status = "unverified"
    elif supported == total:
        status = "supported"
    elif supported + counts.get("partial", 0) > 0:
        status = "partial"
    else:
        status = "unsupported"
    parts = []
    if total:
        parts.append(
            f"{supported} of {total} written statements are supported by the passages they cite"
            + (f" ({corrected} with a citation set by the checker)" if corrected else "")
            + "."
        )
    if removed:
        parts.append(
            f"{removed} sentence{'s' if removed != 1 else ''} the model wrote "
            f"{'were' if removed != 1 else 'was'} removed because no passage supports "
            f"{'them' if removed != 1 else 'it'}."
        )
    return {
        "status": status,
        "statements": total,
        "removed": removed,
        "corrected": corrected,
        "counts": counts,
        "verifier": verifier,
        "explanation": " ".join(parts) or "No written statements to check.",
    }

"""Summary prompts (labelled fields, numbered passages) and parsing the model's reply.

Labelled lines ("RESULTS: …") instead of JSON: small local models follow them far
more reliably, and a reply that is cut off or slightly off-format still yields
every field that was written. Unknown or missing fields become "Not reported."
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.llm import Message
from app.services.summaries.spec import ALIASES, NOT_REPORTED, Field

SYSTEM_PROMPT = f"""You summarize one research paper for a researcher, using ONLY the numbered passages from that paper.

Rules:
- Answer each field in one to three short sentences of plain language.
- End every sentence with the number of the passage that supports it, just before the full stop, like this: "<statement from passage 2> [2]." Use only numbers that appear in the passages.
- If the passages do not answer a field, write exactly "{NOT_REPORTED}" for it. Never guess and never use outside knowledge.
- Write every field on its own line, starting with its label, in the order given, like "PROBLEM: …"."""


@dataclass(frozen=True, slots=True)
class Block:
    number: int
    heading: str  # "3 Approach, p. 4"
    text: str


def paper_line(title: str, year: int | None) -> str:
    return f"Paper: {title}" + (f" ({year})" if year else "")


def field_lines(fields: tuple[Field, ...] | list[Field]) -> str:
    return "\n".join(f"{f.label}: {f.question}" for f in fields)


def group_messages(
    title: str, year: int | None, blocks: list[Block], fields: tuple[Field, ...]
) -> list[Message]:
    passages = "\n\n".join(f"[{b.number}] {b.heading}\n{' '.join(b.text.split())}" for b in blocks)
    user = (
        f"{paper_line(title, year)}\n\nPassages:\n{passages}\n\nFields:\n{field_lines(fields)}"
        f"\n\n{answer_format(fields)}"
    )
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


def answer_format(fields: tuple[Field, ...] | list[Field]) -> str:
    """An explicit answer template. Without it qwen2.5:3b answered 6 of 26 fields with only a
    citation ("MODEL: [3]"); with it 0 of 26 (2 runs, 13 fields, on a sample paper)."""
    lines = "\n".join(
        f"{f.label}: <one to three sentences, each ending with its passage number [n]>"
        for f in fields
    )
    return f"Answer format, one line per field, the text right after the label:\n{lines}"


def has_text(text: str) -> bool:
    """Whether a field says something beyond citation markers ("[3]" alone doesn't)."""
    return bool(re.search(r"[A-Za-z]{3}", re.sub(r"\[[^\]]*\]", "", text)))


def takeaway_messages(
    title: str, year: int | None, drafted: list[tuple[Field, str]], takeaway: Field
) -> list[Message]:
    """Reduce step: the takeaway is written from the drafted fields, citing their passages."""
    notes = "\n".join(f"{f.label}: {text}" for f, text in drafted)
    user = (
        f"{paper_line(title, year)}\n\nSummary so far (the numbers refer to passages of the "
        f"paper):\n{notes}\n\nFields:\n{field_lines([takeaway])}"
    )
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


# "PROBLEM: …", "**Problem:** …", "- Key contribution: …", "### Results: …"
_LABEL_LINE = re.compile(
    r"^\s*(?:[-*•]\s+|#+\s*|\d+[.)]\s+)?(?:\*\*|__)?\s*([A-Za-z][A-Za-z _/-]{1,40}?)\s*"
    r"(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*)$"
)
_NOT_REPORTED = re.compile(
    r"^\W*(not reported|not mentioned|not (?:stated|specified|discussed|described)"
    r"|the passages do not|none reported|n/?a\b)",
    re.I,
)


def _label_key(raw: str, fields: tuple[Field, ...] | list[Field]) -> str | None:
    """Which wanted field a label names: its own label, or a common variant of it."""
    normalized = re.sub(r"[\s/-]+", "_", raw.strip()).upper()
    keys = {f.key for f in fields}
    key = {f.label: f.key for f in fields}.get(normalized) or ALIASES.get(normalized)
    return key if key in keys else None


# "The compute … is not reported in the provided passages." says the same when nothing is cited.
_SAYS_NOT_REPORTED = re.compile(
    r"\b(?:is|are|was|were)\s+not\s+(?:reported|mentioned|specified|stated|provided|given)\b"
    r"|\bdo(?:es)?\s+not\s+(?:report|mention|specify|state|provide)\b|\bnot reported\b",
    re.I,
)


def is_not_reported(text: str) -> bool:
    text = text.strip()
    if not text or _NOT_REPORTED.match(text):
        return True
    return not re.search(r"\[\d", text) and bool(_SAYS_NOT_REPORTED.search(text))


def has_label(reply: str, field: Field) -> bool:
    for line in reply.splitlines():
        match = _LABEL_LINE.match(line)
        if match and _label_key(match.group(1), [field]) == field.key:
            return True
    return False


def parse_fields(reply: str, wanted: tuple[Field, ...] | list[Field]) -> dict[str, str]:
    """Field key → text for each wanted field; missing or "not reported" → NOT_REPORTED."""
    keys = {f.key for f in wanted}
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in reply.splitlines():
        match = _LABEL_LINE.match(line)
        key = _label_key(match.group(1), wanted) if match else None
        if match and key in keys:
            current = key
            found.setdefault(key, [])
            if match.group(2).strip():
                found[key].append(match.group(2).strip())
        elif current is not None and line.strip():
            found[current].append(line.strip())
    result: dict[str, str] = {}
    for field in wanted:
        text = ""
        for part in found.get(field.key, []):
            # Keep bulleted lists as lists (the UI renders Markdown); join wrapped prose.
            text += ("\n" if re.match(r"[-*•]\s|\d+[.)]\s", part) else " ") + part
        text = text.strip()
        text = re.sub(r"(?:\*\*|__)", "", text).strip()
        # "… questions [10] PROBLEM: It also tackles …": the model repeating the field's label.
        text = re.sub(rf"\s*\b{re.escape(field.label)}:\s*", " ", text).strip()
        result[field.key] = NOT_REPORTED if is_not_reported(text) else text
    return result

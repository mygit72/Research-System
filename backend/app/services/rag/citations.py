"""Citation engine: parse [n] markers, drop ones that don't map to evidence, split claims.

A citation can only point at a passage the model was actually given, so an
invented "[7]" (with six passages) is removed and reported, never shown as a link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# [1]  [1, 3]  [1-3]  [1][2]  (also en dash ranges)
_MARKER = re.compile(r"\[(\d+(?:\s*(?:,|-|–)\s*\d+)*)\]")
# Also a boundary: a citation followed by a new capitalized sentence without a full stop
# ("… on all datasets [6] Adapters cut memory …"), as small models sometimes write.
_SENTENCE_END = re.compile(
    r"(?<=[.!?])(?:\s*(?:\[[\d,\s\-–]+\])+)?\s+(?=[A-Z0-9\"“(*-])"
    r"|(?<=\])\s+(?=[A-Z][a-z])"
)
# Some models put the marker first: "[3] Memory drops by 60%. [5] Accuracy is within 1 point."
_PREFIX_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\[\d|[A-Z0-9\"“(*-])")
# Abbreviations that are followed by a capitalised word without ending the sentence. "et al." and
# "No." are left out: they can just as well end one.
_ABBREVIATION_END = re.compile(
    r"(?:^|[\s(\"“])(?:Mr|Mrs|Ms|Dr|Prof|vs|cf|Fig|Figs|Eq|Eqs|Sec|e\.g|i\.e)\.$", re.IGNORECASE
)
_STARTS_WITH_MARKER = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)?\[\d")


def _numbers(group: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"\s*,\s*", group):
        bounds = re.split(r"\s*[-–]\s*", part)
        if len(bounds) == 2:
            low, high = int(bounds[0]), int(bounds[1])
            if 0 < high - low <= 20:
                numbers.extend(range(low, high + 1))
                continue
        numbers.extend(int(b) for b in bounds)
    return numbers


@dataclass
class CitationCheck:
    text: str  # answer with invalid markers removed and markers normalized to [n]
    cited: list[int]  # valid numbers in order of first use
    invalid: list[int] = field(default_factory=list)


# "<statement from passage 2>": the prompt's citation example, copied by small models (3 of 10
# answers in the Phase 13 evaluation run). Bracketed text after a space and before a space,
# punctuation or a marker, starting with a letter — so "<48GB" and "a<b" are left alone.
_PLACEHOLDER = re.compile(r"(?:^|(?<=\s))<([A-Za-z0-9][^<>\n]{0,200})>(?=[\s.,;:!?\[]|$)", re.M)
_TEMPLATE = re.compile(r"^(?:statement(?: from passage \d+)?|passage \d+)$", re.I)


def strip_placeholders(text: str) -> str:
    """Drop copied template placeholders; unwrap real content the model put in <...>."""
    if not _PLACEHOLDER.search(text):
        return text
    removed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        inner = match.group(1).strip()
        if _TEMPLATE.match(inner):
            removed = True
            return ""
        return inner

    cleaned = _PLACEHOLDER.sub(replace, text)
    if removed:
        # The placeholder's sentence is left as just its marker ("[2].") and says nothing.
        cleaned = re.sub(r"(?:^|(?<=[.!?]))\s*(?:\[[\d,\s\-–]+\]\s*)+[.!?](?=\s|$)", "", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def validate_citations(
    answer: str, evidence_count: int, allowed: set[int] | None = None
) -> CitationCheck:
    """`allowed`: the passage numbers this text may cite, when they aren't simply 1..count."""
    answer = strip_placeholders(answer)
    cited: list[int] = []
    invalid: list[int] = []

    def replace(match: re.Match[str]) -> str:
        valid = []
        for number in _numbers(match.group(1)):
            if (number in allowed) if allowed is not None else 1 <= number <= evidence_count:
                valid.append(number)
                if number not in cited:
                    cited.append(number)
            elif number not in invalid:
                invalid.append(number)
        return "".join(f"[{n}]" for n in dict.fromkeys(valid))

    text = _MARKER.sub(replace, answer)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)  # space left where a marker was removed
    return CitationCheck(text=text.strip(), cited=cited, invalid=invalid)


@dataclass
class Claim:
    text: str  # without citation markers
    citations: list[int]


def split_claims(answer: str) -> list[Claim]:
    """Sentences / list items with the citation numbers attached to each."""
    claims: list[Claim] = []
    prefix_style = any(_STARTS_WITH_MARKER.match(line) for line in answer.splitlines())
    for line in answer.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip()
        if not line:
            continue
        for sentence in _split_sentences(line, prefix_style):
            numbers = [n for group in _MARKER.findall(sentence) for n in _numbers(group)]
            text = " ".join(_MARKER.sub("", sentence).split()).strip()
            text = re.sub(r"\s+([.,;:!?])", r"\1", text)
            if len(text) >= 12 and re.search(r"[A-Za-z]{3}", text):
                claims.append(Claim(text=text, citations=list(dict.fromkeys(numbers))))
    return claims


def _split_sentences(line: str, prefix_style: bool = False) -> list[str]:
    parts: list[str] = []
    start = 0
    pattern = _PREFIX_SENTENCE_END if prefix_style else _SENTENCE_END
    for match in pattern.finditer(line):
        if _ABBREVIATION_END.search(line[start : match.start()]):
            continue  # "… datasets such as Mr. TyDi" is not a sentence boundary
        # Keep markers that follow the full stop with the sentence they cite.
        end = match.end()
        parts.append(line[start:end].strip())
        start = end
    parts.append(line[start:].strip())
    # "The contributions are threefold: First, …" holds two claims; check them separately.
    parts = [piece for part in parts for piece in _ENUMERATION.split(part)]
    return [p.strip() for p in parts if p.strip()]


_ENUMERATION = re.compile(r"(?<=:)\s+(?=(?:First(?:ly)?|1\.|\(1\)|\(i\))[\s,])")

"""Rule-based sentence segmentation tuned for scientific text.

Splits on terminal punctuation followed by whitespace and an uppercase letter,
digit or opening bracket — except after abbreviations common in papers
("et al.", "Fig.", "Eq.", "e.g.", "i.e.", "vs.", initials) and inside numbers.
Returns character spans so chunks keep exact offsets.
"""

from __future__ import annotations

import re

_ABBREVIATIONS = {
    "al", "fig", "figs", "eq", "eqs", "e.g", "i.e", "vs", "cf", "etc", "sec", "tab", "ref",
    "refs", "approx", "resp", "dr", "prof", "mr", "ms", "no", "vol", "pp", "ch", "app",
    "st", "jr", "inc", "ltd", "co", "et",
}  # fmt: skip
_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*\s+(?=[A-Z0-9(\[\"“])")


def sentence_spans(text: str, offset: int = 0) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.start() + 1
        word = re.search(r"([A-Za-z.]+)\.$", text[max(0, end - 12) : end])
        token = word.group(1).lower() if word else ""
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
            continue  # "et al." / "Fig." / initials like "A."
        sentence_end = match.end()
        while sentence_end > start and text[sentence_end - 1].isspace():
            sentence_end -= 1
        if sentence_end > start:
            spans.append((offset + start, offset + sentence_end))
        start = match.end()
    tail = text[start:].rstrip()
    if tail.strip():
        spans.append((offset + start, offset + start + len(tail)))
    return spans

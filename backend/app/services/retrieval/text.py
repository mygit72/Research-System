"""Text analysis for lexical retrieval: one analyzer for documents, queries and highlights.

Pipeline: Unicode NFKC → case fold → split on non-alphanumerics → drop stopwords →
Snowball (Porter2) stemming. Using the same analyzer everywhere is what makes
"retrieving" match "retrieval" and lets the UI highlight exactly the words that scored.

Hyphenated terms are split ("fine-tuning" → fine, tune) so they match both spellings;
numbers are kept ("2023", "7b") because they matter in scientific queries.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer

# Letters/digits runs; apostrophes inside words are dropped by the split ("model's" → model, s).
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself
    yourselves s t d ll m o re ve y also et al via""".split()  # noqa: SIM905
)

_stemmer = snowballstemmer.stemmer("english")


@lru_cache(maxsize=200_000)
def stem(word: str) -> str:
    return str(_stemmer.stemWord(word))


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalized text plus, for each normalized char, its index in the original.

    Normalizing char by char keeps offsets exact when a char expands
    (PDF ligature "ﬁ" → "fi", "ß" → "ss"), so highlights still land correctly.
    """
    if text.isascii():
        return text.lower(), list(range(len(text)))
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        normalized = unicodedata.normalize("NFKC", char).casefold()
        chars.append(normalized)
        origin.extend([index] * len(normalized))
    return "".join(chars), origin


@dataclass(frozen=True, slots=True)
class Token:
    term: str  # the analyzed (stemmed) term
    start: int  # character offsets into the original text
    end: int


def tokenize(text: str) -> list[Token]:
    """Analyzed tokens with offsets into `text` (for highlighting)."""
    normalized, origin = _normalize_with_offsets(text)
    tokens = []
    for match in _TOKEN.finditer(normalized):
        word = match.group()
        if word in STOPWORDS or (len(word) == 1 and not word.isdigit()):
            continue
        tokens.append(Token(stem(word), origin[match.start()], origin[match.end() - 1] + 1))
    return tokens


def analyze(text: str) -> list[str]:
    """Analyzed terms (with repeats) — what BM25 indexes and queries with."""
    return [token.term for token in tokenize(text)]


def highlight_spans(text: str, query_terms: set[str]) -> list[tuple[int, int]]:
    """Character spans in `text` whose analyzed term is one of `query_terms`, merged."""
    spans: list[tuple[int, int]] = []
    for token in tokenize(text):
        if token.term in query_terms and token.end > token.start:
            if spans and token.start - spans[-1][1] <= 1:  # join "low-rank", "rank fusion"
                spans[-1] = (spans[-1][0], token.end)
            else:
                spans.append((token.start, token.end))
    return spans


_SAFE_FTS = re.compile(r"[^\w]+", re.UNICODE)


def fts_terms(text: str) -> list[str]:
    """Lower-cased, de-duplicated query words for a PostgreSQL tsquery (PG stems them itself)."""
    words = [w for w in _SAFE_FTS.split(_normalize(text)) if w and w not in STOPWORDS]
    return list(dict.fromkeys(w for w in words if len(w) > 1 or w.isdigit()))

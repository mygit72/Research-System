"""Query understanding before retrieval: intent, entities, time filters, follow-ups.

Rule-based on purpose: every decision is cheap, deterministic and shown in the
trace ("why did it only search 2023+ papers?"). Simple questions are left as is —
the retrieval query only changes when a filter phrase is removed or a follow-up
needs the previous question for context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INTENTS: list[tuple[str, re.Pattern[str]]] = [
    (
        "comparison",
        re.compile(
            r"\b(compare|comparison|versus|vs\.?|differ(ence|ent)?|better than|worse than)\b", re.I
        ),
    ),
    (
        "contradiction_search",
        re.compile(r"\b(contradict\w*|disagree\w*|conflict\w*|inconsistent)\b", re.I),
    ),
    (
        "research_gap",
        re.compile(
            r"\b(gaps?|open (problems?|questions?)|future work|limitations?|unexplored)\b", re.I
        ),
    ),
    (
        "summarization",
        re.compile(r"\b(summari[sz]e|summary|overview|tl;?dr|main (idea|contribution)s?)\b", re.I),
    ),
    (
        "methodology_question",
        re.compile(
            r"\b(how (do|does|did|is|are|was|were)|method\w*|approach|architecture|algorithm|train\w*|implement\w*)\b",
            re.I,
        ),
    ),
    ("dataset_search", re.compile(r"\b(datasets?|benchmarks?|corpus|corpora)\b", re.I)),
    ("model_search", re.compile(r"\b(models?|baselines?|checkpoints?)\b", re.I)),
    ("timeline", re.compile(r"\b(timeline|evolv\w*|over time|history|chronolog\w*)\b", re.I)),
    ("author_search", re.compile(r"\b(who (wrote|proposed|introduced)|authors?)\b", re.I)),
    ("citation_search", re.compile(r"\b(cite[sd]?|citations?|references?)\b", re.I)),
    (
        "literature_search",
        re.compile(r"\b(papers? (about|on)|which papers|find papers|literature)\b", re.I),
    ),
]

_YEAR = r"((?:19|20)\d{2})"
_TEMPORAL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\bbetween {_YEAR} and {_YEAR}\b", re.I), "between"),
    (re.compile(rf"\b(?:after|post-?) ?{_YEAR}\b", re.I), "after"),
    (re.compile(rf"\b(?:since|from) {_YEAR}(?: onwards?)?\b", re.I), "since"),
    (re.compile(rf"\bbefore {_YEAR}\b", re.I), "before"),
    (re.compile(rf"\b(?:in|during|published in) {_YEAR}\b", re.I), "in"),
]
_FOLLOW_UP = re.compile(
    r"^(and|also|what about|how about|why|so)\b|\b(it|its|they|their|them|this|that|these|those)\b",
    re.I,
)
_ABOUT_PAPER = re.compile(
    r"\b(this|the|their|its) (paper|work|study|article|method|approach|model|framework|"
    r"technique|system|experiments?|results?|contributions?|findings)\b|\bproposed?\b|"
    r"\bauthors?\b|\bmain (idea|contribution|finding|result)s?\b",
    re.I,
)
_PAPER_INTENTS = {"summarization", "methodology_question", "research_gap", "dataset_search"}
_ACRONYM = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z0-9-]*\b|\b[A-Z]{2,}[0-9-]*\w*\b")
_QUOTED = re.compile(r"[\"“]([^\"”]{3,80})[\"”]")


@dataclass
class QueryAnalysis:
    question: str
    retrieval_query: str
    intent: str
    intent_cue: str | None
    entities: list[str]
    year_from: int | None = None
    year_to: int | None = None
    temporal_phrase: str | None = None
    follow_up: bool = False
    # Asks about "this paper" / "the authors" / "the proposed method" rather than a topic.
    about_the_paper: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "intent_cue": self.intent_cue,
            "entities": self.entities,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "temporal_phrase": self.temporal_phrase,
            "follow_up": self.follow_up,
            "about_the_paper": self.about_the_paper,
            "retrieval_query": self.retrieval_query,
            "notes": self.notes,
        }


def _temporal(question: str) -> tuple[int | None, int | None, str | None]:
    for pattern, kind in _TEMPORAL:
        match = pattern.search(question)
        if not match:
            continue
        years = [int(y) for y in match.groups()]
        if kind == "between":
            return min(years), max(years), match.group(0)
        year = years[0]
        return {
            "after": (year + 1, None),
            "since": (year, None),
            "before": (None, year - 1),
            "in": (year, year),
        }[kind] + (match.group(0),)
    return None, None, None


def analyze_query(question: str, previous_question: str | None = None) -> QueryAnalysis:
    question = " ".join(question.split())
    intent, cue = "factual_question", None
    for name, pattern in INTENTS:
        match = pattern.search(question)
        if match:
            intent, cue = name, match.group(0)
            break

    entities = list(
        dict.fromkeys(
            [q.strip() for q in _QUOTED.findall(question)]
            + [a for a in _ACRONYM.findall(question) if a.lower() not in {"i", "a"}]
        )
    )
    year_from, year_to, phrase = _temporal(question)
    retrieval_query = question
    notes: list[str] = []
    if phrase:
        # The year range becomes a filter; the phrase itself would only add noise terms.
        retrieval_query = " ".join(question.replace(phrase, " ").split()) or question
        notes.append(f"“{phrase}” applied as a publication-year filter")

    follow_up = bool(
        previous_question
        and (_FOLLOW_UP.search(question) or len(question.split()) <= 4)
        and not entities
    )
    if follow_up and previous_question:
        retrieval_query = f"{previous_question} {retrieval_query}"
        notes.append("Follow-up question: searched together with the previous question")

    return QueryAnalysis(
        question=question,
        retrieval_query=retrieval_query,
        intent=intent,
        intent_cue=cue,
        entities=entities,
        year_from=year_from,
        year_to=year_to,
        temporal_phrase=phrase,
        follow_up=follow_up,
        about_the_paper=bool(_ABOUT_PAPER.search(question)) or intent in _PAPER_INTENTS,
        notes=notes,
    )

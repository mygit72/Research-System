"""Which passages each section group is written from.

For a group (say, experiments → dataset / experiments / results):

1. Lead passages: the first passage of each `lead_kinds` section (the abstract).
2. Section openings: the first passage of every matching section, in reading order
   — where authors say what a (sub)section is about.
3. Topic matches: the remaining passages of those sections, best BM25 match to the
   group's topic words first.
4. No matching section (no headings detected, unusual names): the passages of the
   whole paper that best match the topic words, or the opening of the paper.

Passages are packed until the token budget / passage cap and then put back in
reading order. Every choice records its reason for the trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.document import Chunk
from app.services.llm import count_tokens
from app.services.retrieval.bm25 import BM25Index
from app.services.retrieval.text import analyze
from app.services.summaries.spec import Group

EXCLUDED_SECTIONS = frozenset({"references", "acknowledgments", "appendix"})
MIN_WORDS = 4  # stray fragments (a lone table number "1") only distract the model


@dataclass(slots=True)
class Chosen:
    chunk: Chunk
    reason: str  # lead | section_opening | topic_match | whole_paper | paper_opening
    score: float
    tokens: int


class PaperPassages:
    """A paper's passages with a paper-local BM25 index (statistics from this paper only)."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = sorted(
            (
                c
                for c in chunks
                if c.section_kind not in EXCLUDED_SECTIONS and len(c.text.split()) >= MIN_WORDS
            ),
            key=lambda c: c.chunk_index,
        )
        self.index = BM25Index()
        for chunk in self.chunks:
            self.index.add(chunk.id, analyze(chunk.text))

    def scores(self, query: str) -> dict[Any, float]:
        hits = self.index.search(analyze(query), limit=len(self.chunks))
        return {hit.key: hit.score for hit in hits}

    def select(self, group: Group, token_budget: int, max_passages: int) -> list[Chosen]:
        scores = self.scores(group.query)
        usable = [c for c in self.chunks if c.kind in group.chunk_kinds]
        in_group = [c for c in usable if c.section_kind in group.section_kinds]

        ordered: list[tuple[Chunk, str]] = []
        for kind in group.lead_kinds:
            lead = next((c for c in usable if c.section_kind == kind), None)
            if lead is not None:
                ordered.append((lead, "lead"))
        if in_group:
            openings: list[Chunk] = []
            seen_sections: set[Any] = set()
            for chunk in in_group:
                section = chunk.section_id or chunk.section_title
                if section not in seen_sections:
                    seen_sections.add(section)
                    openings.append(chunk)
            ordered += [(c, "section_opening") for c in openings]
            rest = [c for c in in_group if c not in openings]
            rest.sort(key=lambda c: (-scores.get(c.id, 0.0), c.chunk_index))
            ordered += [(c, "topic_match") for c in rest]
        else:
            matched = [c for c in usable if scores.get(c.id, 0.0) > 0]
            matched.sort(key=lambda c: (-scores[c.id], c.chunk_index))
            ordered += [(c, "whole_paper") for c in matched]
            if not matched:
                ordered += [(c, "paper_opening") for c in usable]

        chosen: list[Chosen] = []
        used: set[Any] = set()
        total = 0
        for chunk, reason in ordered:
            if chunk.id in used or len(chosen) >= max_passages:
                continue
            tokens = count_tokens(chunk.text)
            if chosen and total + tokens > token_budget:
                continue  # a shorter passage later may still fit
            used.add(chunk.id)
            total += tokens
            chosen.append(Chosen(chunk, reason, round(scores.get(chunk.id, 0.0), 4), tokens))
        chosen.sort(key=lambda c: c.chunk.chunk_index)
        return chosen

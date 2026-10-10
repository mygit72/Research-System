"""Research gaps, each linked to the papers behind it and labelled by where it comes from.

- **Stated by the authors**: the limitations and future-work statements of the papers'
  summaries (verified against their passages), grouped by meaning (embeddings, average-
  linkage clustering with a distance threshold). A group shared by several papers is a
  *recurring* limitation.
- **System-generated synthesis**, never presented as the authors' words:
  - *untested combinations*: a method or model used by papers here that no paper here
    evaluates on a dataset that several others use (only within this set of papers);
  - *disagreements*: results that potentially conflict (see `disagreements.py`);
  - *directions*: suggestions written by the language model from the numbered gaps above;
    a direction is kept only if it cites at least one of them.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.config import Settings
from app.services.analysis.digests import Digest, SourceBook, Statement
from app.services.analysis.text import shorten
from app.services.analysis.writing import normalize_citations
from app.services.embeddings import get_embedding_provider
from app.services.knowledge import clustering as algo
from app.services.knowledge.library import Library
from app.services.llm import INSUFFICIENT, Message
from app.services.rag.citations import split_claims, validate_citations

STATED = "Stated by the authors"
SYNTHESIS = "System-generated synthesis"
GROUP_DISTANCE = 0.3  # cosine distance under which two limitation statements are "the same"
MAX_COMBINATIONS = 5
MAX_DIRECTIONS = 4


@dataclass
class Gap:
    id: str
    kind: str  # stated | combination | disagreement
    origin: str  # STATED | SYNTHESIS
    title: str
    text: str
    papers: list[dict[str, Any]] = field(default_factory=list)
    statements: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "origin": self.origin,
            "title": self.title,
            "text": self.text,
            "papers": self.papers,
            "statements": self.statements,
        }


def _paper(d: Digest) -> dict[str, Any]:
    return {"id": str(d.document_id), "title": d.title, "year": d.year}


async def stated_gaps(settings: Settings, digests: list[Digest], book: SourceBook) -> list[Gap]:
    items: list[tuple[Digest, Statement]] = [
        (d, s) for d in digests for s in d.of("limitations", "future_work")
    ]
    if not items:
        return []
    texts = [s.text for _, s in items]
    if len(items) == 1:
        labels = np.zeros(1, dtype=int)
    else:
        provider = get_embedding_provider(settings)
        vectors = await asyncio.to_thread(provider.embed_documents, texts)
        distances = algo.cosine_distances(np.asarray(vectors))
        labels = algo.agglomerative(distances, threshold=GROUP_DISTANCE)
    groups: dict[int, list[tuple[Digest, Statement]]] = {}
    for label, item in zip(labels.tolist(), items, strict=True):
        groups.setdefault(label, []).append(item)
    ordered = sorted(
        groups.values(),
        key=lambda g: (-len({d.document_id for d, _ in g}), -len(g), g[0][0].title),
    )
    gaps: list[Gap] = []
    for group in ordered:
        papers = list({d.document_id: _paper(d) for d, _ in group}.values())
        recurring = len(papers) > 1
        fields = {s.field for _, s in group}
        kind_word = "Future work" if fields == {"future_work"} else "Limitation"
        gaps.append(
            Gap(
                id=f"G{len(gaps) + 1}",
                kind="stated",
                origin=STATED,
                # Keyword titles ("layers, layer, adding") read badly; the statements say it.
                title=(
                    f"Recurring {kind_word.lower()} ({len(papers)} papers)"
                    if recurring
                    else f"{kind_word} ({shorten(papers[0]['title'], 60)})"
                ),
                text=group[0][1].text,
                papers=papers,
                statements=[
                    {
                        "document": _paper(d),
                        "field": s.field,
                        "text": s.text,
                        "citations": book.cite(s),
                    }
                    for d, s in group
                ],
            )
        )
    return gaps


def combination_gaps(digests: list[Digest], library: Library, start: int) -> list[Gap]:
    """Methods / models × datasets that no paper in this set evaluates together."""
    ids = {d.document_id for d in digests}
    by_paper = {d.document_id: d for d in digests}
    uses: dict[str, set[Any]] = {}
    kinds: dict[str, str] = {}
    proposed: set[str] = set()
    for link in library.links:
        if link.document_id not in ids or link.relation not in ("proposes", "uses"):
            continue
        entity = library.entities[link.entity_id]
        if entity.type in ("method", "model", "dataset"):
            uses.setdefault(entity.name, set()).add(link.document_id)
            kinds[entity.name] = entity.type
            if link.relation == "proposes":
                proposed.add(entity.name)
    datasets = {n: p for n, p in uses.items() if kinds[n] == "dataset" and len(p) >= 2}
    # A method or model counts if a paper here proposes it or at least two use it: one
    # mention (GPT-4 as a judge, BLOOM in a table) gave "untested: GPT-4 on QQP".
    methods = {
        n: p for n, p in uses.items() if kinds[n] != "dataset" and (len(p) >= 2 or n in proposed)
    }
    # Generic building blocks ("Fine-tuning", "Adam") pair with everything: skip methods used
    # by most of the set.
    methods = {n: p for n, p in methods.items() if len(p) <= max(1, math.ceil(len(ids) / 2))}
    candidates = []
    for method, method_papers in methods.items():
        for dataset, dataset_papers in datasets.items():
            if method_papers & dataset_papers:
                continue  # some paper here already evaluates it there
            candidates.append((len(dataset_papers) * len(method_papers), method, dataset))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    # One per method and one per dataset: "T5 on MNLI / MRPC / QQP / RTE" says the same thing.
    chosen, used_methods, used_datasets = [], set(), set()
    for candidate in candidates:
        if candidate[1] in used_methods or candidate[2] in used_datasets:
            continue
        chosen.append(candidate)
        used_methods.add(candidate[1])
        used_datasets.add(candidate[2])
    gaps: list[Gap] = []
    for _, method, dataset in chosen[:MAX_COMBINATIONS]:
        papers = sorted(uses[method] | uses[dataset], key=lambda i: by_paper[i].title)
        gaps.append(
            Gap(
                id=f"G{start + len(gaps)}",
                kind="combination",
                origin=SYNTHESIS,
                title=f"Untested here: {method} on {dataset}",
                text=(
                    f"{method} is used by {len(uses[method])} of these papers and {dataset} by "
                    f"{len(uses[dataset])}, but none of them evaluates {method} on {dataset}. "
                    "Based only on the papers in this set."
                ),
                papers=[_paper(by_paper[i]) for i in papers],
            )
        )
    return gaps


def disagreement_gaps(disagreements: list[dict[str, Any]], start: int) -> list[Gap]:
    gaps: list[Gap] = []
    for item in disagreements:
        shared = ", ".join(item["shared"][:3])
        gaps.append(
            Gap(
                id=f"G{start + len(gaps)}",
                kind="disagreement",
                origin=SYNTHESIS,
                title=f"Conflicting findings on {shared}",
                text=(
                    f"“{item['claim_a']['document']['title']}” and "
                    f"“{item['claim_b']['document']['title']}” report statements that may "
                    "conflict; their setups differ, so the question is open."
                ),
                papers=[item["claim_a"]["document"], item["claim_b"]["document"]],
            )
        )
    return gaps


# --- directions (language model) -------------------------------------------------------------

DIRECTIONS_SYSTEM = """You are helping a researcher find research directions. You get a numbered list of research gaps found in their papers.

Rules:
- Suggest up to 4 concrete research directions, one per line, each a single sentence.
- Each direction must address one or more of the listed gaps: end the sentence with the numbers of those gaps, like this: "<direction> [2]."
- Use only the listed gaps. Do not invent results, datasets or papers that are not mentioned."""


def directions_messages(gaps: list[Gap]) -> list[Message]:
    blocks = "\n\n".join(f"[{i}] {g.title}\n{g.text}" for i, g in enumerate(gaps, 1))
    return [
        Message("system", DIRECTIONS_SYSTEM),
        Message(
            "user",
            f"Evidence:\n{blocks}\n\nQuestion: Which research directions would address these gaps?",
        ),
    ]


def parse_directions(reply: str, gaps: list[Gap]) -> list[dict[str, Any]]:
    if reply.strip().startswith(INSUFFICIENT[:40]):
        return []
    reply = re.sub(r"(?im)^\s*(?:\*\*)?direction\s*\d*\s*(?:\*\*)?\s*:\s*", "", reply)
    text = validate_citations(normalize_citations(reply, len(gaps)), len(gaps)).text
    directions = []
    for claim in split_claims(text):
        cited = [n for n in claim.citations if 1 <= n <= len(gaps)]
        sentence = claim.text.strip(" -•*")
        if not cited or len(sentence.split()) < 4:
            continue  # a direction must say which gap it addresses
        based_on = [gaps[n - 1] for n in dict.fromkeys(cited)]
        papers = list({p["id"]: p for g in based_on for p in g.papers}.values())
        directions.append(
            {
                "text": sentence,
                "based_on": [g.id for g in based_on],
                "papers": papers,
                "origin": SYNTHESIS,
            }
        )
        if len(directions) == MAX_DIRECTIONS:
            break
    return directions


def gap_counts(gaps: list[Gap]) -> dict[str, int]:
    return dict(Counter(g.kind for g in gaps))

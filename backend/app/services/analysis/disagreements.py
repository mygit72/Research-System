"""Potential disagreements between papers.

Candidates are pairs of verified statements (results, limitations, contributions,
takeaways) from two papers that work on something in common — a dataset, model, method,
task or metric both papers use, named in both statements. Each pair is scored in both
directions by the NLI model ("does A contradict B?"); with the lexical test verifier, which
can't see contradictions, an explicit polarity rule stands in (one statement says
improves / outperforms, the other says does not improve / fails / worse).

A candidate is reported as a *potential* disagreement with both claims, their passages,
the shared setup, and what differs between the papers (datasets, models, metrics, years) —
the usual reason two papers report different things. The system never says which paper is
right.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.services.analysis.digests import Digest, SourceBook, Statement
from app.services.knowledge.library import Library
from app.services.rag.verify import Verifier

FIELDS = ("results", "limitations", "contribution", "takeaway", "method")
NLI_THRESHOLD = 0.6
MAX_PAIRS = 400  # NLI calls per report (both directions count as one pair)
MAX_REPORTED = 8

_POSITIVE = re.compile(
    r"\b(?:improv\w*|outperform\w*|better|gains?|increas\w*|helps?|effective|surpass\w*|"
    r"state-of-the-art|matches|comparable)\b",
    re.I,
)
_NEGATIVE = re.compile(
    r"\b(?:(?:does|do|did)\s+not\s+(?:improve|help|outperform)|no\s+(?:significant\s+)?"
    r"(?:improvement|gain|benefit)|fails?\s+to|worse|degrad\w*|hurts?|underperform\w*|"
    r"not\s+effective|ineffective)\b",
    re.I,
)


@dataclass
class Candidate:
    a: tuple[Digest, Statement]
    b: tuple[Digest, Statement]
    shared: list[str]
    score: float
    method: str


def _mentions(text: str, names: list[str]) -> bool:
    lowered = text.casefold()
    return any(re.search(rf"(?<![\w-]){re.escape(n.casefold())}(?![\w])", lowered) for n in names)


def _polarity(text: str) -> int:
    if _NEGATIVE.search(text):
        return -1
    if _POSITIVE.search(text):
        return 1
    return 0


def _entity_context(library: Library, document_id: uuid.UUID) -> dict[str, dict[str, list[str]]]:
    """type → {entity id: [name, aliases…]} of what the paper proposes or uses."""
    out: dict[str, dict[str, list[str]]] = {}
    for link in library.links_of(document_id):
        if link.relation not in ("proposes", "uses"):
            continue
        entity = library.entities[link.entity_id]
        out.setdefault(entity.type, {})[str(entity.id)] = [entity.name, *entity.aliases]
    return out


def find_disagreements(
    digests: list[Digest], library: Library, verifier: Verifier | None
) -> list[Candidate]:
    contexts = {d.document_id: _entity_context(library, d.document_id) for d in digests}
    use_nli = verifier is not None and not verifier.name.startswith("lexical")
    pairs: list[tuple[tuple[Digest, Statement], tuple[Digest, Statement], list[str]]] = []
    for da, db in combinations(digests, 2):
        ca, cb = contexts[da.document_id], contexts[db.document_id]
        shared_ids = {
            entity_id: names
            for kind in set(ca) & set(cb)
            for entity_id, names in ca[kind].items()
            if entity_id in cb[kind]
        }
        if not shared_ids:
            continue
        for sa in da.of(*FIELDS):
            for sb in db.of(*FIELDS):
                shared = [
                    names[0]
                    for names in shared_ids.values()
                    if _mentions(sa.text, names) and _mentions(sb.text, names)
                ]
                if shared:
                    pairs.append(((da, sa), (db, sb), shared))
    pairs = pairs[:MAX_PAIRS]
    found: list[Candidate] = []
    if use_nli and pairs and verifier is not None:
        scores = verifier.entailment(
            [(a[1].text, b[1].text) for a, b, _ in pairs]
            + [(b[1].text, a[1].text) for a, b, _ in pairs]
        )
        n = len(pairs)
        for index, (a, b, shared) in enumerate(pairs):
            contradiction = max(scores[index][1], scores[n + index][1])
            if contradiction >= NLI_THRESHOLD:
                found.append(Candidate(a, b, shared, round(contradiction, 3), "nli"))
    else:
        for a, b, shared in pairs:
            if _polarity(a[1].text) * _polarity(b[1].text) == -1:
                found.append(Candidate(a, b, shared, 1.0, "polarity"))
    # One per paper pair (the strongest), strongest first.
    best: dict[tuple[uuid.UUID, uuid.UUID], Candidate] = {}
    for c in found:
        key = (c.a[0].document_id, c.b[0].document_id)
        if key not in best or c.score > best[key].score:
            best[key] = c
    return sorted(best.values(), key=lambda c: -c.score)[:MAX_REPORTED]


def describe(candidate: Candidate, library: Library, book: SourceBook) -> dict[str, Any]:
    """The JSON shown in the report: both claims with sources, shared setup, differences."""
    (da, sa), (db, sb) = candidate.a, candidate.b
    ca = _entity_context(library, da.document_id)
    cb = _entity_context(library, db.document_id)

    def names(context: dict[str, dict[str, list[str]]], kind: str) -> set[str]:
        return {v[0] for v in context.get(kind, {}).values()}

    differences = {}
    for kind in ("dataset", "model", "metric", "task"):
        only_a, only_b = names(ca, kind) - names(cb, kind), names(cb, kind) - names(ca, kind)
        if only_a or only_b:
            differences[kind] = {"a": sorted(only_a)[:6], "b": sorted(only_b)[:6]}
    return {
        "claim_a": {
            "document": {"id": str(da.document_id), "title": da.title, "year": da.year},
            "text": sa.text,
            "field": sa.field,
            "citations": book.cite(sa),
        },
        "claim_b": {
            "document": {"id": str(db.document_id), "title": db.title, "year": db.year},
            "text": sb.text,
            "field": sb.field,
            "citations": book.cite(sb),
        },
        "shared": candidate.shared,
        "differences": differences,
        "score": candidate.score,
        "detector": candidate.method,
        "label": "Potential disagreement",
        "note": "The papers may differ in setup; this flags the statements, it doesn't say "
        "which is right.",
    }

"""Read models over the library snapshot: entities, authors, timeline, related work.

Everything here is derived from the user's own papers. Counts and "first seen" years
describe *the library*, not the field — the UI words them that way, and author pages
show documented facts only (papers, co-authors, affiliations, years), never judgments.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from app.core.errors import NotFoundError
from app.services.knowledge.library import Library, Link, Paper, institution_key

STRONG = ("proposes", "uses")
TYPE_ORDER = {"dataset": 0, "model": 1, "method": 2, "task": 3, "metric": 4}


def paper_brief(library: Library, paper: Paper) -> dict[str, Any]:
    # The cleaned author list (same as the author pages), not the raw metadata string, which
    # can hold parser artefacts like "Language Understanding".
    names = [library.authors[key].name for key in paper.authors]
    authors = ", ".join(names[:3]) + (f", +{len(names) - 3}" if len(names) > 3 else "")
    return {
        "id": str(paper.id),
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "authors": authors,
        "topic": library.topics.get(paper.id),
    }


def _entity_brief(library: Library, entity_id: uuid.UUID, **extra: Any) -> dict[str, Any]:
    entity = library.entities[entity_id]
    return {"id": str(entity.id), "type": entity.type, "name": entity.name, **extra}


# --- entities ------------------------------------------------------------------------------------


def list_entities(
    library: Library,
    *,
    entity_type: str | None = None,
    query: str | None = None,
    include_mentions: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    per_entity: dict[uuid.UUID, list[Link]] = defaultdict(list)
    for link in library.links:
        per_entity[link.entity_id].append(link)
    q = (query or "").casefold().strip()
    rows: list[dict[str, Any]] = []
    for entity_id, links in per_entity.items():
        entity = library.entities[entity_id]
        if entity_type and entity.type != entity_type:
            continue
        if (
            q
            and q not in entity.name.casefold()
            and not any(q in a.casefold() for a in entity.aliases)
        ):
            continue
        strong = [link for link in links if link.relation in STRONG]
        if not strong and not include_mentions:
            continue
        years = [y for link in links if (y := library.papers[link.document_id].year)]
        rows.append(
            {
                "id": str(entity.id),
                "type": entity.type,
                "name": entity.name,
                "aliases": entity.aliases[:6],
                "source": entity.source,
                "paper_count": len({link.document_id for link in strong}),
                "mention_count": len(
                    {link.document_id for link in links if link.relation == "mentions"}
                ),
                "proposed_by": len(
                    {link.document_id for link in links if link.relation == "proposes"}
                ),
                "first_year": min(years) if years else None,
                "last_year": max(years) if years else None,
                "has_info": bool(entity.info),
            }
        )
    rows.sort(key=lambda r: (-r["paper_count"], -r["mention_count"], r["name"].casefold()))
    return rows[:limit]


def entity_detail(library: Library, entity_id: uuid.UUID) -> dict[str, Any]:
    entity = library.entities.get(entity_id)
    if entity is None:
        raise NotFoundError("This entity isn't in your library.")
    links = sorted(
        library.papers_of_entity(entity_id),
        key=lambda link: (
            ("proposes", "uses", "mentions").index(link.relation),
            -(library.papers[link.document_id].year or 0),
        ),
    )
    papers = [
        {
            **paper_brief(library, library.papers[link.document_id]),
            "relation": link.relation,
            "mentions": link.mentions,
            "variants": link.variants,
            "evidence": link.evidence,
        }
        for link in links
    ]
    # Co-occurring entities: linked (proposes/uses) to the same papers.
    docs = {link.document_id for link in links if link.relation in STRONG}
    together: Counter[uuid.UUID] = Counter()
    for link in library.links:
        if link.document_id in docs and link.entity_id != entity_id and link.relation in STRONG:
            together[link.entity_id] += 1
    related = [
        _entity_brief(library, other, shared_papers=count)
        for other, count in sorted(
            together.items(), key=lambda kv: (-kv[1], library.entities[kv[0]].name)
        )
        if count >= 1
    ][:12]
    years = Counter(library.papers[d].year for d in docs if library.papers[d].year)
    return {
        "id": str(entity.id),
        "type": entity.type,
        "name": entity.name,
        "aliases": entity.aliases,
        "source": entity.source,
        "info": entity.info,
        "papers": papers,
        "related": related,
        "years": [{"year": y, "papers": c} for y, c in sorted(years.items())],
    }


def document_entities(library: Library, document_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = [
        {
            **_entity_brief(library, link.entity_id),
            "relation": link.relation,
            "mentions": link.mentions,
            "variants": link.variants,
            "evidence": link.evidence,
            "paper_count": len(
                {
                    other.document_id
                    for other in library.papers_of_entity(link.entity_id)
                    if other.relation in STRONG
                }
            ),
        }
        for link in library.links_of(document_id)
    ]
    rows.sort(
        key=lambda r: (
            ("proposes", "uses", "mentions").index(r["relation"]),
            TYPE_ORDER.get(r["type"], 9),
            -r["mentions"],
        )
    )
    return rows


# --- authors -------------------------------------------------------------------------------------


def list_authors(
    library: Library, query: str | None = None, limit: int = 300
) -> list[dict[str, Any]]:
    q = (query or "").casefold().strip()
    rows: list[dict[str, Any]] = []
    for author in library.authors.values():
        if q and q not in author.name.casefold():
            continue
        years = [y for d in author.papers if (y := library.papers[d].year)]
        rows.append(
            {
                "key": author.key,
                "name": author.name,
                "paper_count": len(author.papers),
                "institutions": sorted(library.institutions[i].name for i in author.institutions)[
                    :3
                ],
                "first_year": min(years) if years else None,
                "last_year": max(years) if years else None,
            }
        )
    rows.sort(key=lambda r: (-r["paper_count"], r["name"].casefold()))
    return rows[:limit]


def author_detail(library: Library, key: str) -> dict[str, Any]:
    author = library.authors.get(key)
    if author is None:
        raise NotFoundError("This author isn't in your library.")
    papers = sorted(
        (library.papers[d] for d in author.papers), key=lambda p: (-(p.year or 0), p.title)
    )
    coauthors: Counter[str] = Counter()
    for paper in papers:
        for other in paper.authors:
            if other != key:
                coauthors[other] += 1
    topics: Counter[str] = Counter()
    for paper in papers:
        if topic := library.topics.get(paper.id):
            topics[topic["name"]] += 1
    keywords: Counter[str] = Counter(k for p in papers for k in p.keywords)
    entity_counts: Counter[uuid.UUID] = Counter()
    for paper in papers:
        for link in library.links_of(paper.id):
            if link.relation in STRONG and library.entities[link.entity_id].type in (
                "dataset",
                "method",
                "model",
                "task",
            ):
                entity_counts[link.entity_id] += 1
    timeline = Counter(p.year for p in papers if p.year)
    return {
        "key": author.key,
        "name": author.name,
        "spellings": sorted(author.spellings),
        "paper_count": len(papers),
        "papers": [paper_brief(library, p) for p in papers],
        "coauthors": [
            {"key": k, "name": library.authors[k].name, "shared_papers": c}
            for k, c in coauthors.most_common(20)
        ],
        "institutions": sorted(library.institutions[i].name for i in author.institutions),
        "topics": [{"name": n, "papers": c} for n, c in topics.most_common()],
        "keywords": [k for k, _ in keywords.most_common(10)],
        "entities": [
            _entity_brief(library, e, papers=c)
            for e, c in sorted(
                entity_counts.items(), key=lambda kv: (-kv[1], library.entities[kv[0]].name)
            )
        ][:15],
        "years": [{"year": y, "papers": c} for y, c in sorted(timeline.items())],
    }


# --- timeline ------------------------------------------------------------------------------------


def timeline(
    library: Library,
    *,
    topic: int | None = None,
    author: str | None = None,
    venue: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    def keep(paper: Paper) -> bool:
        if topic is not None and (library.topics.get(paper.id) or {}).get("id") != topic:
            return False
        if author and author not in paper.authors:
            return False
        if venue and institution_key(paper.venue or "") != institution_key(venue):
            return False
        return entity_id is None or any(
            link.entity_id == entity_id and link.relation in STRONG
            for link in library.links_of(paper.id)
        )

    selected = [p for p in library.papers.values() if keep(p)]
    # First year each entity appears (proposed or used) in the *whole* library.
    first_seen: dict[uuid.UUID, int] = {}
    for link in library.links:
        year = library.papers[link.document_id].year
        if link.relation in STRONG and year:
            first_seen[link.entity_id] = min(year, first_seen.get(link.entity_id, year))

    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    undated = []
    for paper in sorted(selected, key=lambda p: (p.year or 0, p.title)):
        links = library.links_of(paper.id)
        proposes = [
            _entity_brief(library, link.entity_id) for link in links if link.relation == "proposes"
        ]
        uses = sorted(
            (link for link in links if link.relation == "uses"),
            key=lambda link: (
                TYPE_ORDER.get(library.entities[link.entity_id].type, 9),
                -link.score,
            ),
        )
        item = {
            **paper_brief(library, paper),
            "proposes": proposes,
            "uses": [_entity_brief(library, link.entity_id) for link in uses[:8]],
        }
        if paper.year:
            by_year[paper.year].append(item)
        else:
            undated.append(item)

    years = []
    for year in sorted(by_year):
        papers_in_year = {uuid.UUID(p["id"]) for p in by_year[year]}
        firsts = sorted(
            {
                link.entity_id
                for link in library.links
                if link.document_id in papers_in_year
                and link.relation in STRONG
                and first_seen.get(link.entity_id) == year
                and library.entities[link.entity_id].type in ("method", "model", "dataset")
            },
            key=lambda e: (TYPE_ORDER.get(library.entities[e].type, 9), library.entities[e].name),
        )
        years.append(
            {
                "year": year,
                "papers": by_year[year],
                "first_seen": [_entity_brief(library, e) for e in firsts][:12],
            }
        )

    # Filter options from the whole library.
    venues = Counter(p.venue for p in library.papers.values() if p.venue)
    methods = Counter(
        link.entity_id
        for link in library.links
        if link.relation in STRONG and library.entities[link.entity_id].type in ("method", "model")
    )
    return {
        "years": years,
        "undated": undated,
        "paper_count": len(selected),
        "filters": {
            "topics": [
                {"id": c["id"], "name": c["name"], "size": c["size"]}
                for c in (library.topic_run or {}).get("clusters", [])
            ],
            "authors": [
                {"key": a.key, "name": a.name, "papers": len(a.papers)}
                for a in sorted(library.authors.values(), key=lambda a: (-len(a.papers), a.name))
            ][:100],
            "venues": [{"name": v, "papers": c} for v, c in venues.most_common(50)],
            "methods": [
                _entity_brief(library, e, papers=c) for e, c in methods.most_common(60) if c >= 1
            ],
        },
    }


# --- related work --------------------------------------------------------------------------------


def related_work(library: Library, document_id: uuid.UUID) -> dict[str, Any]:
    paper = library.papers.get(document_id)
    if paper is None:
        raise NotFoundError("This paper isn't ready yet.")
    cites = [
        {
            **paper_brief(library, library.papers[c.cited]),
            "match": c.match,
            "reference": c.reference,
        }
        for c in library.citations
        if c.citing == document_id
    ]
    cited_by = [
        {
            **paper_brief(library, library.papers[c.citing]),
            "match": c.match,
            "reference": c.reference,
        }
        for c in library.citations
        if c.cited == document_id
    ]
    mine = {
        link.entity_id: link.relation
        for link in library.links_of(document_id)
        if link.relation in STRONG
    }
    shared: dict[uuid.UUID, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for link in library.links:
        if (
            link.document_id == document_id
            or link.entity_id not in mine
            or link.relation not in STRONG
        ):
            continue
        entity = library.entities[link.entity_id]
        if entity.type in ("dataset", "method", "model", "task"):
            shared[link.document_id][entity.type].append(entity.name)
    # Rank by distinctive overlap: a shared dataset says more than a shared generic method.
    df = Counter(link.entity_id for link in library.links if link.relation in STRONG)
    by_name = {library.entities[e].name: e for e in mine}

    def weight(names: dict[str, list[str]]) -> float:
        return sum(1 / df[by_name[n]] for ns in names.values() for n in ns if n in by_name)

    ranked = sorted(shared.items(), key=lambda kv: -weight(kv[1]))
    same = [
        {
            **paper_brief(library, library.papers[doc_id]),
            "shared": {t: sorted(ns) for t, ns in names.items()},
            "score": round(weight(names), 3),
        }
        for doc_id, names in ranked[:8]
    ]
    authors = set(paper.authors)
    same_authors = [
        {
            **paper_brief(library, other),
            "shared_authors": [library.authors[a].name for a in other.authors if a in authors],
        }
        for other in library.papers.values()
        if other.id != document_id and authors & set(other.authors)
    ]
    return {
        "cites": cites,
        "cited_by": cited_by,
        "shared_entities": same,
        "same_authors": same_authors[:8],
        "topic": library.topics.get(document_id),
    }

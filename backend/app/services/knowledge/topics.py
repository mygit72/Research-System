"""Topic clustering of the library: paper vectors → clusters → terms → names.

- Vectors: the paper-level embedding (title + abstract + keywords) written at indexing
  time, read back from the vector store. Papers indexed with another embedding model
  than most of the library can't be compared and are listed as excluded.
- Clusters: K-Means (k given, or chosen by silhouette), agglomerative (average
  linkage) or HDBSCAN (can leave papers unclustered as "noise").
- Terms: class-based TF-IDF (c-TF-IDF, as in BERTopic): a term scores high when it is
  frequent in this cluster's papers and rare across the other clusters.
- Names: written by the language model from each cluster's titles, terms and
  entities (a background job); until then, and if the model isn't available, the
  top terms are the name. The UI says which one it is.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ValidationError
from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentStatus,
    DocumentVersion,
    IndexStatus,
)
from app.models.knowledge import DocumentEntity, Entity, TopicClustering
from app.services.knowledge import clustering as algo
from app.services.vectorstore import collection_name, get_vector_store

NAMING_JOB = "topics.name"
NAMING_PROMPT_VERSION = "2"
METHODS = ("auto", "kmeans", "agglomerative", "hdbscan")
MAX_TERMS = 8

_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")
_STOP = frozenset(
    """the and for with from that this these those are was were been being have has had
    our we their they them its it into onto over under than then also such using use used
    uses based via can could may might will would should which while where when what who
    how all any each both more most other some only same very not but nor yet per one two
    three new show shows shown propose proposed proposes approach approaches method methods
    paper papers work results result study task tasks model models data performance improve
    improves improved first second state art large small different several many much well
    able across between within without however further thus here there achieve achieves
    existing previous recent simple strong significantly significant set number large-scale
    present presents introduce introduces demonstrate demonstrates experiments experimental
    """.split()  # noqa: SIM905
)


@dataclass
class LibraryVectors:
    model: str | None
    document_ids: list[uuid.UUID]
    version_ids: list[uuid.UUID]
    vectors: np.ndarray
    excluded: list[dict[str, Any]]

    @property
    def fingerprint(self) -> str:
        raw = "|".join([self.model or "", *sorted(str(v) for v in self.version_ids)])
        return hashlib.sha256(raw.encode()).hexdigest()


async def library_vectors(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> LibraryVectors:
    rows = (
        await session.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .where(Document.user_id == user_id, Document.status == DocumentStatus.READY)
            .order_by(Document.created_at)
        )
    ).all()
    excluded: list[dict[str, Any]] = []
    indexed = []
    for doc, version in rows:
        if doc.index_status != IndexStatus.INDEXED or not version.embedding_model:
            excluded.append({"document_id": str(doc.id), "reason": "not_indexed"})
        else:
            indexed.append((doc, version))
    models = Counter((v.embedding_model, v.embedding_dimension) for _, v in indexed)
    if not models:
        return LibraryVectors(None, [], [], np.zeros((0, 0)), excluded)
    (model, dimension), _ = models.most_common(1)[0]
    chosen = []
    for doc, version in indexed:
        if (version.embedding_model, version.embedding_dimension) == (model, dimension):
            chosen.append((doc, version))
        else:
            excluded.append({"document_id": str(doc.id), "reason": "other_embedding_model"})
    assert model is not None and dimension is not None
    store = get_vector_store(settings)
    name = collection_name("documents", model, dimension)
    found = await asyncio.to_thread(store.get_vectors, name, [d.id for d, _ in chosen])
    ids, versions, vectors = [], [], []
    for doc, version in chosen:
        if doc.id in found:
            ids.append(doc.id)
            versions.append(version.id)
            vectors.append(found[doc.id])
        else:
            excluded.append({"document_id": str(doc.id), "reason": "no_vector"})
    matrix = np.vstack(vectors) if vectors else np.zeros((0, dimension))
    return LibraryVectors(model, ids, versions, matrix, excluded)


# --- terms ---------------------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    words = [w.strip("-") for w in _TOKEN.findall(text.lower())]
    words = [w for w in words if len(w) > 2 and w not in _STOP and not w.isdigit()]
    bigrams = [f"{a} {b}" for a, b in pairwise(words)]
    return words + bigrams


def ctfidf_terms(cluster_texts: list[list[str]], top: int = MAX_TERMS) -> list[list[str]]:
    """c-TF-IDF: tf(t, c) / |c| · log(1 + A / f(t)), A = average words per cluster."""
    counts = [Counter(t for text in texts for t in _tokens(text)) for texts in cluster_texts]
    total = Counter[str]()
    for c in counts:
        total.update(c)
    sizes = [max(1, sum(c.values())) for c in counts]
    average = sum(sizes) / max(1, len(sizes))
    result = []
    for c, size in zip(counts, sizes, strict=True):
        scored = sorted(
            ((tf / size) * math.log(1 + average / total[t]), t)
            for t, tf in c.items()
            if tf >= 2 or len(cluster_texts) == 1
        )
        picked: list[str] = []
        for _, term in reversed(scored):
            # Skip a word already covered by a chosen bigram, and vice versa.
            if any(term in p.split() or p in term.split() for p in picked):
                continue
            picked.append(term)
            if len(picked) == top:
                break
        result.append(picked)
    return result


def fallback_name(terms: list[str], entities: list[str]) -> str:
    if entities[:2] and terms:
        return f"{terms[0].capitalize()} ({', '.join(entities[:2])})"
    if terms:
        return " · ".join(t.capitalize() for t in terms[:3])
    return "Unnamed topic"


# --- running -------------------------------------------------------------------------------------


@dataclass
class ClusterRequest:
    method: str = "auto"
    k: int | None = None
    min_cluster_size: int | None = None


def _labels(request: ClusterRequest, vectors: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    n = len(vectors)
    distances = algo.cosine_distances(vectors)
    quality: dict[str, Any] = {}
    if request.method == "auto":
        auto = algo.auto_kmeans(vectors, k_max=min(8, max(2, n // 2)))
        labels, quality["k_scores"], quality["chosen_k"] = auto.result.labels, auto.scores, auto.k
    elif request.method == "kmeans":
        k = max(1, min(request.k or 3, n))
        labels = algo.kmeans(vectors, k).labels
    elif request.method == "agglomerative":
        k = max(1, min(request.k or 3, n))
        labels = algo.agglomerative(distances, k=k)
    elif request.method == "hdbscan":
        size = request.min_cluster_size or max(2, min(5, n // 6))
        result = algo.hdbscan(distances, min_cluster_size=size)
        labels = result.labels
        quality["stabilities"] = result.stabilities
        quality["min_cluster_size"] = size
    else:
        raise ValidationError(f"Unknown clustering method “{request.method}”.")
    score = algo.silhouette(distances, labels)
    quality["silhouette"] = None if score is None else round(score, 4)
    quality["noise"] = int((labels == algo.NOISE).sum())
    return labels, quality


async def run_clustering(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, request: ClusterRequest
) -> TopicClustering:
    if request.method not in METHODS:
        raise ValidationError(f"Unknown clustering method “{request.method}”.")
    library = await library_vectors(session, settings, user_id)
    if len(library.document_ids) < 3:
        raise ValidationError(
            "Topic clustering needs at least 3 searchable papers.",
            hint="Upload more papers, or wait until they finish indexing.",
        )
    labels, quality = await asyncio.to_thread(_labels, request, library.vectors)
    coords = await asyncio.to_thread(algo.pca_2d, library.vectors)
    quality["variance_2d"] = round(algo.explained_variance_2d(library.vectors), 4)

    meta_rows = (
        await session.execute(
            select(Document.id, Document.title, Document.year, DocumentMetadata)
            .outerjoin(DocumentMetadata, DocumentMetadata.version_id == Document.current_version_id)
            .where(Document.id.in_(library.document_ids))
        )
    ).all()
    texts = {
        doc_id: " ".join(
            [title, (meta.abstract or "") if meta else "", " ".join(meta.keywords) if meta else ""]
        )
        for doc_id, title, _, meta in meta_rows
    }
    titles = {doc_id: title for doc_id, title, _, _ in meta_rows}
    entity_rows = (
        await session.execute(
            select(DocumentEntity.document_id, Entity.name, Entity.type, DocumentEntity.relation)
            .join(Entity, Entity.id == DocumentEntity.entity_id)
            .where(
                DocumentEntity.document_id.in_(library.document_ids),
                DocumentEntity.relation.in_(("proposes", "uses")),
                Entity.type.in_(("method", "model", "dataset", "task")),
            )
        )
    ).all()

    cluster_ids = sorted({int(label) for label in labels if label != algo.NOISE})
    members = {
        c: [library.document_ids[i] for i, label in enumerate(labels) if label == c]
        for c in cluster_ids
    }
    terms = ctfidf_terms([[texts.get(d, "") for d in members[c]] for c in cluster_ids])
    paper_entities: dict[uuid.UUID, set[str]] = {}
    for doc_id, name, _, _ in entity_rows:
        paper_entities.setdefault(doc_id, set()).add(name)
    entity_df = Counter(n for names in paper_entities.values() for n in names)
    library_size = len(library.document_ids)
    clusters = []
    for c, cluster_terms in zip(cluster_ids, terms, strict=True):
        docs = members[c]
        inside = Counter(n for d in docs for n in paper_entities.get(d, ()))

        def distinctive(name: str, inside: Counter[str] = inside, size: int = len(docs)) -> float:
            # Used by most of this cluster's papers, by few papers elsewhere (an IDF weight).
            return (inside[name] / size) * math.log(1 + library_size / entity_df[name])

        ranked = sorted(inside, key=lambda n: (-distinctive(n), n))
        top_entities = [n for n in ranked if inside[n] * 2 >= len(docs)][:5]
        clusters.append(
            {
                "id": c,
                "name": fallback_name(cluster_terms, top_entities),
                "name_source": "terms",
                "terms": cluster_terms,
                "entities": top_entities,
                "document_ids": [str(d) for d in members[c]],
                "size": len(members[c]),
            }
        )
    points = [
        {
            "document_id": str(doc_id),
            "title": titles.get(doc_id, ""),
            "x": round(float(coords[i, 0]), 4),
            "y": round(float(coords[i, 1]), 4),
            "cluster": int(labels[i]),
        }
        for i, doc_id in enumerate(library.document_ids)
    ]
    run = TopicClustering(
        user_id=user_id,
        method=request.method,
        params={"k": request.k, "min_cluster_size": request.min_cluster_size},
        fingerprint=library.fingerprint,
        embedding_model=library.model or "",
        result={
            "clusters": clusters,
            "points": points,
            "quality": quality,
            "excluded": library.excluded,
            "paper_count": len(library.document_ids),
        },
        naming_status="pending",
    )
    session.add(run)
    await session.flush()
    return run


async def latest_clustering(session: AsyncSession, user_id: uuid.UUID) -> TopicClustering | None:
    return (
        await session.execute(
            select(TopicClustering)
            .where(TopicClustering.user_id == user_id)
            .order_by(TopicClustering.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def stale_reason(
    session: AsyncSession, settings: Settings, run: TopicClustering
) -> str | None:
    library = await library_vectors(session, settings, run.user_id)
    if library.fingerprint == run.fingerprint:
        return None
    before = run.result.get("paper_count", 0)
    now = len(library.document_ids)
    if now != before:
        return f"Your library changed since these topics were made ({before} → {now} papers)."
    return "Some papers were reprocessed since these topics were made."


async def topic_of_documents(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """document id → {id, name} from the latest clustering (empty when there is none)."""
    run = await latest_clustering(session, user_id)
    if run is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for cluster in run.result.get("clusters", []):
        for doc_id in cluster["document_ids"]:
            out[doc_id] = {"id": cluster["id"], "name": cluster["name"], "run_id": str(run.id)}
    return out


async def clustering_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(TopicClustering)
                .where(TopicClustering.user_id == user_id)
            )
        ).scalar_one()
    )


# --- naming --------------------------------------------------------------------------------------
# One short call per cluster. Measured on qwen2.5:3b (12 real papers, 3 clusters, 2 runs): a single
# prompt listing every cluster gave identifier-style names attached to the wrong clusters (0/6
# grounded, the same every run); one prompt per cluster gave 6/6 ("Document Retrieval" for
# ColBERT / DPR / RAG), at ~2 s per cluster.

NAME_QUESTION = "What research topic do these papers share?"
_NAME_STOP = frozenset(
    """and for the of in with on a an to via over by models model learning research papers
    methods method approach approaches study topic""".split()  # noqa: SIM905
)


def naming_prompt(cluster: dict[str, Any], titles: dict[str, str]) -> str:
    paper_titles = [titles.get(d, "") for d in cluster["document_ids"]][:8]
    return (
        "Here is a group of research papers.\n"
        f"Papers: {' | '.join(t for t in paper_titles if t)}\n"
        f"Key terms: {', '.join(cluster['terms'][:8])}\n"
        f"Common methods/datasets: {', '.join(cluster['entities']) or 'none'}\n\n"
        f"{NAME_QUESTION} Answer with a topic name of 2 to 5 plain English words "
        '(e.g. "Neural machine translation"), nothing else.'
    )


def clean_name(reply: str) -> str | None:
    """The first line, without labels, quotes or identifier style; None if it isn't a name."""
    line = next((part for part in reply.splitlines() if part.strip()), "")
    line = re.sub(r"^\s*(?:topic(?: name)?\s*:\s*)", "", line.strip().strip("*\"'`"), flags=re.I)
    name = re.sub(r"\s+", " ", line.replace("_", " ")).strip().strip("*\"'`.")
    if not 1 <= len(name.split()) <= 7 or len(name) > 60:
        return None
    return name


def _name_words(text: str) -> set[str]:
    # 5-letter prefixes: "retrieval" ~ "retriever", "adaptation" ~ "adapters".
    return {
        w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _NAME_STOP
    }


def grounded(
    name: str, cluster: dict[str, Any], clusters: list[dict[str, Any]], titles: dict[str, str]
) -> bool:
    """A name must share a word with its own cluster (titles, terms, entities), and more words
    with it than with any other cluster — a cheap guard against generic or swapped names."""

    def vocabulary(c: dict[str, Any]) -> set[str]:
        parts = [*(titles.get(d, "") for d in c["document_ids"]), *c["terms"], *c["entities"]]
        return _name_words(" ".join(parts))

    words = _name_words(name)
    own = len(words & vocabulary(cluster))
    return own > 0 and all(
        own > len(words & vocabulary(o)) for o in clusters if o["id"] != cluster["id"]
    )

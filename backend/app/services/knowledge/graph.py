"""The research knowledge graph.

Nodes: paper, author, institution, dataset, model, method, metric, task, topic.
Edges (directed, from the paper side):

    paper ─authored_by→ author ─affiliated_with→ institution
    paper ─cites→ paper                    (references matched to papers in the library)
    paper ─proposes→ method|model|…        (what the paper introduces)
    paper ─uses_dataset / uses_model / uses_method→ …
    paper ─evaluates_on→ task              paper ─reports_metric→ metric
    paper ─mentions→ …                     (in passing; hidden unless asked for)
    paper ─in_topic→ topic                 (latest topic clustering)

`GraphStore` is the seam for a graph database: the NetworkX implementation builds the
graph in memory from the relational tables (the source of truth) on demand; a Neo4j
store would sync the same nodes and edges and answer the same four queries
(overview, neighbors, search, path) in Cypher.

"Importance" is PageRank on the undirected graph, so the overview starts from the
papers and entities that hold the library together instead of an unreadable hairball.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Protocol

import networkx as nx
import numpy as np

from app.services.knowledge.library import Library

NODE_TYPES = (
    "paper",
    "author",
    "institution",
    "dataset",
    "model",
    "method",
    "metric",
    "task",
    "topic",
)
RELATIONS = (
    "authored_by",
    "affiliated_with",
    "cites",
    "proposes",
    "uses_dataset",
    "uses_model",
    "uses_method",
    "evaluates_on",
    "reports_metric",
    "mentions",
    "in_topic",
)
DEFAULT_TYPES = ("paper", "author", "dataset", "model", "method", "task", "topic")
USE_RELATION = {
    "dataset": "uses_dataset",
    "model": "uses_model",
    "method": "uses_method",
    "task": "evaluates_on",
    "metric": "reports_metric",
}


@dataclass
class GraphView:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    hidden: dict[str, int] = field(default_factory=dict)  # node type → nodes not shown
    total_nodes: int = 0
    total_edges: int = 0


class GraphStore(Protocol):
    def overview(
        self, types: set[str], relations: set[str], limit: int, focus: str | None
    ) -> GraphView: ...
    def neighbors(
        self, node_id: str, types: set[str], relations: set[str], limit: int
    ) -> GraphView: ...
    def search(self, query: str, types: set[str], limit: int) -> list[dict[str, Any]]: ...
    def path(self, source: str, target: str, relations: set[str]) -> GraphView | None: ...


def paper_node(document_id: uuid.UUID | str) -> str:
    return f"paper:{document_id}"


def entity_node(entity_id: uuid.UUID | str) -> str:
    return f"entity:{entity_id}"


def build_graph(library: Library) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for paper in library.papers.values():
        g.add_node(
            paper_node(paper.id),
            type="paper",
            label=paper.title,
            ref=str(paper.id),
            year=paper.year,
            venue=paper.venue,
            authors=paper.authors_display,
        )
        for key in paper.authors:
            author = library.authors[key]
            node = f"author:{key}"
            if node not in g:
                g.add_node(
                    node, type="author", label=author.name, ref=key, papers=len(author.papers)
                )
            g.add_edge(
                paper_node(paper.id), node, key="authored_by", relation="authored_by", weight=1.0
            )
    for author in library.authors.values():
        for inst_key in author.institutions:
            inst = library.institutions[inst_key]
            node = f"institution:{inst_key}"
            if node not in g:
                g.add_node(
                    node, type="institution", label=inst.name, ref=inst_key, papers=len(inst.papers)
                )
            g.add_edge(
                f"author:{author.key}",
                node,
                key="affiliated_with",
                relation="affiliated_with",
                weight=1.0,
            )
    for citation in library.citations:
        g.add_edge(
            paper_node(citation.citing),
            paper_node(citation.cited),
            key="cites",
            relation="cites",
            weight=1.0,
            match=citation.match,
        )
    paper_counts = Counter(link.entity_id for link in library.links if link.relation != "mentions")
    for link in library.links:
        entity = library.entities[link.entity_id]
        node = entity_node(entity.id)
        if node not in g:
            g.add_node(
                node,
                type=entity.type,
                label=entity.name,
                ref=str(entity.id),
                papers=paper_counts.get(entity.id, 0),
                source=entity.source,
            )
        relation = (
            link.relation
            if link.relation in ("proposes", "mentions")
            else USE_RELATION.get(entity.type, "uses_method")
        )
        g.add_edge(
            paper_node(link.document_id),
            node,
            key=relation,
            relation=relation,
            weight=min(1.0, 0.3 + link.score / 20),
            mentions=link.mentions,
        )
    if library.topic_run:
        for cluster in library.topic_run["clusters"]:
            node = f"topic:{cluster['id']}"
            g.add_node(
                node,
                type="topic",
                label=cluster["name"],
                ref=str(cluster["id"]),
                papers=cluster["size"],
            )
            for doc_id in cluster["document_ids"]:
                if paper_node(doc_id) in g:
                    g.add_edge(
                        paper_node(doc_id), node, key="in_topic", relation="in_topic", weight=1.0
                    )
    return g


def pagerank(g: nx.Graph, damping: float = 0.85, iterations: int = 60) -> dict[str, float]:
    """Weighted PageRank by power iteration on the undirected graph (dangling mass spread
    uniformly). Small and explicit, instead of pulling in scipy for networkx's version."""
    nodes = list(g.nodes)
    if not nodes:
        return {}
    index = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    w = np.zeros((n, n))
    for a, b, data in g.edges(data=True):
        weight = float(data.get("weight", 1.0))
        w[index[a], index[b]] += weight
        w[index[b], index[a]] += weight
    out = w.sum(axis=1)
    dangling = out == 0
    transition = np.divide(w, out[:, None], out=np.zeros_like(w), where=out[:, None] > 0)
    rank = np.full(n, 1.0 / n)
    for _ in range(iterations):
        new = (1 - damping) / n + damping * (rank @ transition + rank[dangling].sum() / n)
        if np.abs(new - rank).sum() < 1e-9:
            rank = new
            break
        rank = new
    return {node: float(rank[index[node]]) for node in nodes}


class NetworkXGraphStore:
    def __init__(self, graph: nx.MultiDiGraph) -> None:
        self.g = graph
        self.rank = pagerank(nx.Graph(graph))

    # --- helpers ---------------------------------------------------------------------------

    def _sub(self, types: set[str], relations: set[str]) -> nx.MultiDiGraph:
        """Nodes of the given types (isolated ones included) and edges of the given relations."""
        sub = nx.MultiDiGraph()
        sub.add_nodes_from((n, d) for n, d in self.g.nodes(data=True) if d["type"] in types)
        sub.add_edges_from(
            (a, b, k, d)
            for a, b, k, d in self.g.edges(keys=True, data=True)
            if d["relation"] in relations and a in sub and b in sub
        )
        return sub

    def _node(self, node: str, sub: nx.MultiDiGraph, visible: set[str]) -> dict[str, Any]:
        data = dict(self.g.nodes[node])
        neighbors = set(nx.all_neighbors(sub, node)) if node in sub else set()
        return {
            "id": node,
            "type": data.pop("type"),
            "label": data.pop("label"),
            "importance": round(self.rank.get(node, 0.0) * len(self.g), 4),
            "degree": len(neighbors),
            # Neighbors the current filters would show but this view doesn't ("expand").
            "hidden_neighbors": len(neighbors - visible),
            "data": data,
        }

    def _view(self, nodes: set[str], sub: nx.MultiDiGraph, types: set[str]) -> GraphView:
        edges = [
            {
                "source": a,
                "target": b,
                "relation": data["relation"],
                "weight": round(float(data.get("weight", 1.0)), 3),
            }
            for a, b, data in sub.subgraph(nodes).edges(data=True)
        ]
        all_types = Counter(d["type"] for _, d in sub.nodes(data=True))
        shown = Counter(self.g.nodes[n]["type"] for n in nodes)
        return GraphView(
            nodes=sorted(
                (self._node(n, sub, nodes) for n in nodes),
                key=lambda x: (-x["importance"], x["id"]),
            ),
            edges=edges,
            hidden={t: c - shown.get(t, 0) for t, c in all_types.items() if c > shown.get(t, 0)},
            total_nodes=sub.number_of_nodes(),
            total_edges=sub.number_of_edges(),
        )

    # --- queries ---------------------------------------------------------------------------

    def overview(
        self, types: set[str], relations: set[str], limit: int, focus: str | None = None
    ) -> GraphView:
        sub = self._sub(types, relations)
        if focus and focus in self.g:
            return self.neighbors(focus, types, relations, limit)
        papers = [n for n in sub if sub.nodes[n]["type"] == "paper"]
        papers.sort(key=lambda n: -self.rank.get(n, 0.0))
        chosen = set(papers[: max(1, int(limit * 0.4))])
        # Then the entities that connect the most chosen papers (ties: importance).
        candidates = Counter[str]()
        for paper in chosen:
            for nb in set(nx.all_neighbors(sub, paper)):
                if sub.nodes[nb]["type"] != "paper":
                    candidates[nb] += 1
        others = sorted(
            candidates,
            key=lambda n: (-(candidates[n] >= 2), -candidates[n], -self.rank.get(n, 0.0)),
        )
        for node in others:
            if len(chosen) >= limit:
                break
            chosen.add(node)
        # Topics are few and give the overview its structure: always include them.
        chosen |= {n for n in sub if sub.nodes[n]["type"] == "topic"}
        return self._view(chosen, sub, types)

    def neighbors(
        self, node_id: str, types: set[str], relations: set[str], limit: int
    ) -> GraphView:
        if node_id not in self.g:
            return GraphView([], [])
        sub = self._sub(types | {self.g.nodes[node_id]["type"]}, relations)
        ranked = sorted(
            set(nx.all_neighbors(sub, node_id)),
            key=lambda n: (
                -max(d.get("weight", 1.0) for d in _edge_data(sub, node_id, n)),
                -self.rank.get(n, 0.0),
            ),
        )
        return self._view({node_id, *ranked[:limit]}, sub, types)

    def search(self, query: str, types: set[str], limit: int) -> list[dict[str, Any]]:
        q = query.casefold().strip()
        if not q:
            return []
        hits = []
        for node, data in self.g.nodes(data=True):
            if data["type"] not in types:
                continue
            label = str(data["label"]).casefold()
            if q in label:
                hits.append((0 if label.startswith(q) else 1, -self.rank.get(node, 0.0), node))
        everything = self._sub(set(NODE_TYPES), set(RELATIONS))
        return [self._node(node, everything, set()) for _, _, node in sorted(hits)[:limit]]

    def path(self, source: str, target: str, relations: set[str]) -> GraphView | None:
        if source not in self.g or target not in self.g:
            return None
        undirected = nx.Graph()
        undirected.add_nodes_from(self.g.nodes)
        for a, b, data in self.g.edges(data=True):
            if data["relation"] in relations:
                undirected.add_edge(a, b)
        try:
            nodes = nx.shortest_path(undirected, source, target)
        except nx.NetworkXNoPath:
            return None
        view = self._view(set(nodes), self._sub(set(NODE_TYPES), relations), set(NODE_TYPES))
        order = {n: i for i, n in enumerate(nodes)}
        view.nodes.sort(key=lambda n: order[n["id"]])
        # Only the edges along the path (the subgraph may hold shortcuts between its nodes).
        steps = {frozenset(pair) for pair in pairwise(nodes)}
        view.edges = [e for e in view.edges if frozenset((e["source"], e["target"])) in steps]
        return view


def _edge_data(g: nx.MultiDiGraph, a: str, b: str) -> list[dict[str, Any]]:
    data = list((g.get_edge_data(a, b) or {}).values()) + list(
        (g.get_edge_data(b, a) or {}).values()
    )
    return data or [{"weight": 1.0}]


_stores: dict[uuid.UUID, tuple[str, NetworkXGraphStore]] = {}


def graph_store(library: Library) -> NetworkXGraphStore:
    """Per-user store, rebuilt when the library snapshot changes."""
    cached = _stores.get(library.user_id)
    if cached is not None and cached[0] == library.fingerprint:
        return cached[1]
    store = NetworkXGraphStore(build_graph(library))
    _stores[library.user_id] = (library.fingerprint, store)
    if len(_stores) > 32:
        _stores.pop(next(iter(_stores)))
    return store

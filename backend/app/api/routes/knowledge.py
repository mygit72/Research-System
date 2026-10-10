"""Knowledge graph, entities, authors, timeline, related work and topic clustering."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.core.errors import NotFoundError, ValidationError
from app.models.knowledge import TopicClustering
from app.schemas.knowledge import (
    AuthorDetail,
    AuthorListItem,
    ClusterRequestIn,
    DocumentEntityOut,
    EntityDetail,
    EntityListItem,
    GraphEdge,
    GraphNode,
    GraphOut,
    RelatedWorkOut,
    TimelineOut,
    TopicCluster,
    TopicClusteringOut,
    TopicPoint,
    TopicsOut,
)
from app.services import organization as org
from app.services.knowledge import views
from app.services.knowledge.entities import ensure_entities
from app.services.knowledge.graph import (
    DEFAULT_TYPES,
    NODE_TYPES,
    RELATIONS,
    GraphView,
    graph_store,
    paper_node,
)
from app.services.knowledge.library import Library, load_library
from app.services.knowledge.topics import (
    NAMING_JOB,
    ClusterRequest,
    latest_clustering,
    library_vectors,
    run_clustering,
    stale_reason,
)

router = APIRouter(tags=["knowledge"])


async def _library(db: DbSession, user: CurrentUser) -> Library:
    await ensure_entities(db, user.id)
    return await load_library(db, user.id)


def _types(value: str | None, default: tuple[str, ...] = DEFAULT_TYPES) -> set[str]:
    if not value:
        return set(default)
    chosen = {t.strip() for t in value.split(",") if t.strip()}
    unknown = chosen - set(NODE_TYPES)
    if unknown:
        raise ValidationError(f"Unknown node type: {', '.join(sorted(unknown))}.")
    return chosen


def _relations(value: str | None, include_mentions: bool) -> set[str]:
    if value:
        chosen = {r.strip() for r in value.split(",") if r.strip()}
        unknown = chosen - set(RELATIONS)
        if unknown:
            raise ValidationError(f"Unknown relation: {', '.join(sorted(unknown))}.")
        return chosen
    return {r for r in RELATIONS if include_mentions or r != "mentions"}


def _graph_out(view: GraphView, library: Library) -> GraphOut:
    return GraphOut(
        nodes=[GraphNode(**n) for n in view.nodes],
        edges=[GraphEdge(**e) for e in view.edges],
        hidden=view.hidden,
        total_nodes=view.total_nodes,
        total_edges=view.total_edges,
        paper_count=len(library.papers),
        entity_status={
            "entities": len(library.entities),
            "links": len(library.links),
            "citations": len(library.citations),
            "authors": len(library.authors),
            "topics": len((library.topic_run or {}).get("clusters", [])),
        },
    )


# --- graph ---------------------------------------------------------------------------------------


@router.get(
    "/graph",
    response_model=GraphOut,
    summary="A manageable overview of the knowledge graph",
    description="The most important papers (PageRank) and the entities that connect most of "
    "them, up to `limit` nodes. `focus` (a node id) returns that node's neighbourhood instead. "
    "`types` / `relations`: comma-separated filters; `mentions` edges only with "
    "`include_mentions=true`.",
)
async def graph_overview(
    user: CurrentUser,
    db: DbSession,
    types: str | None = Query(default=None, examples=["paper,dataset,method"]),
    relations: str | None = Query(default=None),
    include_mentions: bool = False,
    limit: int = Query(default=60, ge=5, le=400),
    focus: str | None = None,
) -> GraphOut:
    library = await _library(db, user)
    store = graph_store(library)
    view = store.overview(_types(types), _relations(relations, include_mentions), limit, focus)
    return _graph_out(view, library)


@router.get("/graph/neighbors", response_model=GraphOut, summary="Expand one node")
async def graph_neighbors(
    user: CurrentUser,
    db: DbSession,
    node: str,
    types: str | None = None,
    relations: str | None = None,
    include_mentions: bool = False,
    limit: int = Query(default=30, ge=1, le=200),
) -> GraphOut:
    library = await _library(db, user)
    store = graph_store(library)
    if node not in store.g:
        raise NotFoundError("This node isn't in your knowledge graph.")
    view = store.neighbors(
        node, _types(types, NODE_TYPES), _relations(relations, include_mentions), limit
    )
    return _graph_out(view, library)


@router.get("/graph/search", response_model=list[GraphNode], summary="Find nodes by name")
async def graph_search(
    user: CurrentUser,
    db: DbSession,
    q: str = Query(min_length=1, max_length=200),
    types: str | None = None,
    limit: int = Query(default=12, ge=1, le=50),
) -> list[GraphNode]:
    store = graph_store(await _library(db, user))
    return [GraphNode(**n) for n in store.search(q, _types(types, NODE_TYPES), limit)]


@router.get(
    "/graph/path",
    response_model=GraphOut,
    summary="How two nodes are connected (shortest path)",
)
async def graph_path(
    user: CurrentUser,
    db: DbSession,
    source: str,
    target: str,
    include_mentions: bool = False,
) -> GraphOut:
    library = await _library(db, user)
    store = graph_store(library)
    view = store.path(source, target, _relations(None, include_mentions))
    if view is None:
        raise NotFoundError("These two aren't connected in your library.")
    return _graph_out(view, library)


@router.get(
    "/papers/{document_id}/knowledge-graph",
    response_model=GraphOut,
    summary="A paper's neighbourhood in the knowledge graph",
)
async def paper_graph(
    document_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    include_mentions: bool = False,
    limit: int = Query(default=40, ge=1, le=200),
) -> GraphOut:
    await org.get_document(db, user.id, document_id)
    library = await _library(db, user)
    store = graph_store(library)
    if paper_node(document_id) not in store.g:
        raise NotFoundError("This paper isn't ready yet.")
    view = store.neighbors(
        paper_node(document_id), set(NODE_TYPES), _relations(None, include_mentions), limit
    )
    return _graph_out(view, library)


# --- entities ------------------------------------------------------------------------------------


@router.get(
    "/entities",
    response_model=list[EntityListItem],
    summary="Datasets, models, methods, metrics and tasks found in your papers",
)
async def list_entities(
    user: CurrentUser,
    db: DbSession,
    type: str | None = Query(default=None, pattern="^(dataset|model|method|metric|task)$"),
    q: str | None = Query(default=None, max_length=200),
    include_mentions: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[EntityListItem]:
    library = await _library(db, user)
    rows = views.list_entities(
        library, entity_type=type, query=q, include_mentions=include_mentions, limit=limit
    )
    return [EntityListItem(**r) for r in rows]


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def read_entity(entity_id: uuid.UUID, user: CurrentUser, db: DbSession) -> EntityDetail:
    return EntityDetail(**views.entity_detail(await _library(db, user), entity_id))


@router.get(
    "/documents/{document_id}/entities",
    response_model=list[DocumentEntityOut],
    summary="What a paper proposes, uses and mentions, with evidence",
)
async def document_entities(
    document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[DocumentEntityOut]:
    await org.get_document(db, user.id, document_id)
    library = await _library(db, user)
    return [DocumentEntityOut(**r) for r in views.document_entities(library, document_id)]


@router.get(
    "/documents/{document_id}/related",
    response_model=RelatedWorkOut,
    summary="Related work in your library: citations, shared datasets/methods, same authors",
)
async def related_work(document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RelatedWorkOut:
    await org.get_document(db, user.id, document_id)
    return RelatedWorkOut(**views.related_work(await _library(db, user), document_id))


# --- authors -------------------------------------------------------------------------------------


@router.get("/authors", response_model=list[AuthorListItem])
async def list_authors(
    user: CurrentUser,
    db: DbSession,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=300, ge=1, le=1000),
) -> list[AuthorListItem]:
    return [AuthorListItem(**r) for r in views.list_authors(await _library(db, user), q, limit)]


@router.get(
    "/authors/{key}",
    response_model=AuthorDetail,
    summary="An author's papers, co-authors, affiliations and topics in your library",
)
async def read_author(key: str, user: CurrentUser, db: DbSession) -> AuthorDetail:
    return AuthorDetail(**views.author_detail(await _library(db, user), key))


# --- timeline ------------------------------------------------------------------------------------


@router.get("/timeline", response_model=TimelineOut, summary="Your papers by year")
async def read_timeline(
    user: CurrentUser,
    db: DbSession,
    topic: int | None = None,
    author: str | None = None,
    venue: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> TimelineOut:
    library = await _library(db, user)
    return TimelineOut(
        **views.timeline(library, topic=topic, author=author, venue=venue, entity_id=entity_id)
    )


# --- topics --------------------------------------------------------------------------------------


async def _topics_out(
    db: DbSession, settings: SettingsDep, run: TopicClustering
) -> TopicClusteringOut:
    out = TopicClusteringOut.model_validate(run)
    result = run.result or {}
    out.clusters = [TopicCluster(**c) for c in result.get("clusters", [])]
    out.points = [TopicPoint(**p) for p in result.get("points", [])]
    out.quality = result.get("quality", {})
    out.excluded = result.get("excluded", [])
    out.paper_count = result.get("paper_count", 0)
    out.stale = await stale_reason(db, settings, run)
    return out


@router.get("/topics", response_model=TopicsOut, summary="The latest topic clustering")
async def read_topics(user: CurrentUser, db: DbSession, settings: SettingsDep) -> TopicsOut:
    run = await latest_clustering(db, user.id)
    library = await library_vectors(db, settings, user.id)
    return TopicsOut(
        clustering=await _topics_out(db, settings, run) if run else None,
        searchable_papers=len(library.document_ids),
    )


@router.post(
    "/topics",
    response_model=TopicClusteringOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cluster your papers into topics",
    description="`method`: auto (K-Means, k chosen by silhouette) | kmeans | agglomerative | "
    "hdbscan. Clusters are computed immediately and named from their top terms; a background "
    "job then asks the language model for readable names.",
)
async def create_topics(
    body: ClusterRequestIn,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> TopicClusteringOut:
    await ensure_entities(db, user.id)  # cluster descriptions list each topic's entities
    run = await run_clustering(
        db,
        settings,
        user.id,
        ClusterRequest(body.method, body.k, body.min_cluster_size),
    )
    if run.result.get("clusters"):
        job = await jobs.enqueue(
            user.id,
            NAMING_JOB,
            payload={"clustering_id": str(run.id)},
            subject_type="topic_clustering",
            subject_id=run.id,
        )
        run.job_id = job.id
    else:
        run.naming_status = "done"
    await db.flush()
    await db.refresh(run)
    return await _topics_out(db, settings, run)

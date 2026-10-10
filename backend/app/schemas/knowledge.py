from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel

# --- graph ---------------------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str  # "paper:<uuid>", "entity:<uuid>", "author:<key>", "institution:<key>", "topic:<n>"
    type: str
    label: str
    importance: float
    degree: int
    hidden_neighbors: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = 1.0


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hidden: dict[str, int] = Field(default_factory=dict)
    total_nodes: int = 0
    total_edges: int = 0
    paper_count: int = 0
    entity_status: dict[str, Any] = Field(default_factory=dict)


# --- entities ------------------------------------------------------------------------------------


class EntityEvidence(BaseModel):
    quote: str
    page: int
    section_kind: str
    section_id: str | None = None
    paragraph_index: int | None = None
    surface: str = ""


class EntityBrief(BaseModel):
    id: uuid.UUID
    type: str
    name: str


class PaperBrief(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None = None
    venue: str | None = None
    authors: str = ""
    topic: dict[str, Any] | None = None


class EntityListItem(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    aliases: list[str]
    source: str
    paper_count: int
    mention_count: int
    proposed_by: int
    first_year: int | None
    last_year: int | None
    has_info: bool


class EntityPaper(PaperBrief):
    relation: str
    mentions: int
    variants: list[str]
    evidence: list[EntityEvidence]


class RelatedEntity(EntityBrief):
    shared_papers: int


class YearCount(BaseModel):
    year: int
    papers: int


class EntityDetail(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    aliases: list[str]
    source: str
    info: dict[str, str]
    papers: list[EntityPaper]
    related: list[RelatedEntity]
    years: list[YearCount]


class DocumentEntityOut(EntityBrief):
    relation: str
    mentions: int
    variants: list[str]
    evidence: list[EntityEvidence]
    paper_count: int


# --- authors -------------------------------------------------------------------------------------


class AuthorListItem(BaseModel):
    key: str
    name: str
    paper_count: int
    institutions: list[str]
    first_year: int | None
    last_year: int | None


class Coauthor(BaseModel):
    key: str
    name: str
    shared_papers: int


class AuthorEntity(EntityBrief):
    papers: int


class NamedCount(BaseModel):
    name: str
    papers: int


class AuthorDetail(BaseModel):
    key: str
    name: str
    spellings: list[str]
    paper_count: int
    papers: list[PaperBrief]
    coauthors: list[Coauthor]
    institutions: list[str]
    topics: list[NamedCount]
    keywords: list[str]
    entities: list[AuthorEntity]
    years: list[YearCount]


# --- timeline ------------------------------------------------------------------------------------


class TimelinePaper(PaperBrief):
    proposes: list[EntityBrief]
    uses: list[EntityBrief]


class TimelineYear(BaseModel):
    year: int
    papers: list[TimelinePaper]
    first_seen: list[EntityBrief]


class TimelineOut(BaseModel):
    years: list[TimelineYear]
    undated: list[TimelinePaper]
    paper_count: int
    filters: dict[str, list[dict[str, Any]]]


# --- related work --------------------------------------------------------------------------------


class CitationLinkOut(PaperBrief):
    match: str
    reference: str


class SharedEntitiesPaper(PaperBrief):
    shared: dict[str, list[str]]
    score: float


class SameAuthorsPaper(PaperBrief):
    shared_authors: list[str]


class RelatedWorkOut(BaseModel):
    cites: list[CitationLinkOut]
    cited_by: list[CitationLinkOut]
    shared_entities: list[SharedEntitiesPaper]
    same_authors: list[SameAuthorsPaper]
    topic: dict[str, Any] | None = None


# --- topics --------------------------------------------------------------------------------------


class ClusterRequestIn(BaseModel):
    method: Literal["auto", "kmeans", "agglomerative", "hdbscan"] = "auto"
    k: int | None = Field(default=None, ge=1, le=30, description="kmeans / agglomerative")
    min_cluster_size: int | None = Field(default=None, ge=2, le=50, description="hdbscan")


class TopicCluster(BaseModel):
    id: int
    name: str
    name_source: str  # terms | model
    terms: list[str]
    entities: list[str]
    document_ids: list[uuid.UUID]
    size: int


class TopicPoint(BaseModel):
    document_id: uuid.UUID
    title: str
    x: float
    y: float
    cluster: int  # -1 = noise (HDBSCAN)


class TopicClusteringOut(APIModel):
    id: uuid.UUID
    method: str
    params: dict[str, Any]
    embedding_model: str
    naming_status: str
    naming_model: str | None
    error_message: str | None
    created_at: datetime
    clusters: list[TopicCluster] = Field(default_factory=list)
    points: list[TopicPoint] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    paper_count: int = 0
    stale: str | None = None


class TopicsOut(BaseModel):
    clustering: TopicClusteringOut | None
    searchable_papers: int

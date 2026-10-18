"""Scoring arXiv candidates against a watch's topic (and, if linked, its project's research
question) by embedding cosine similarity. No LLM is involved here — relevance is scored purely
by the embedding model already used for retrieval."""

from __future__ import annotations

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.agent import AgentWatch
from app.models.project import ResearchProject
from app.services.embeddings import get_embedding_provider
from app.services.knowledge.clustering import normalize
from app.services.retrieval.dense import embed_query


async def anchor_text(session: AsyncSession, watch: AgentWatch) -> tuple[str, str | None]:
    """The watch's topic, and its linked project's research question, if any."""
    if watch.project_id is None:
        return watch.query, None
    project = await session.get(ResearchProject, watch.project_id)
    question = project.question.strip() if project and project.question.strip() else None
    return watch.query, question


def anchor_vector(settings: Settings, topic: str, project_question: str | None) -> np.ndarray:
    """A single relevance vector: the topic's embedding, averaged 50/50 with the linked
    project's question embedding when there is one, re-normalized to unit length."""
    provider = get_embedding_provider(settings)
    topic_vector = embed_query(provider, topic)
    if not project_question:
        return topic_vector
    question_vector = embed_query(provider, project_question)
    averaged = (topic_vector + question_vector) / 2
    return normalize(averaged.reshape(1, -1))[0]


def score_candidates(settings: Settings, anchor: np.ndarray, abstracts: list[str]) -> np.ndarray:
    """Cosine similarity of each abstract to the anchor vector (both sides are already
    L2-normalized by the embedding provider, so a plain dot product is the cosine)."""
    if not abstracts:
        return np.zeros(0)
    provider = get_embedding_provider(settings)
    vectors = provider.embed_documents(abstracts)
    return vectors @ anchor

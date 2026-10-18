"""Public, no-login views of a Research Watch — only for a watch its owner has explicitly
marked public (`AgentWatch.is_public`). No route here takes a `CurrentUser`; that absence is
what makes it unauthenticated in this codebase (auth is enforced per-route via that dependency
parameter, not a router-level gate). Exposes only what's already public on arXiv: title,
authors, abstract, arXiv id, published date, score, the LLM blurb. Never the owner's identity,
`document_id` (their private library), `import_status`, or anything about their other watches.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.agent import PublicDigestEntryOut, PublicWatchOut
from app.schemas.common import Page
from app.services.agent import service as agent

router = APIRouter(prefix="/public/watches", tags=["public"])


@router.get("/{watch_id}", response_model=PublicWatchOut)
async def get_public_watch(watch_id: uuid.UUID, db: DbSession) -> PublicWatchOut:
    return PublicWatchOut.model_validate(await agent.get_public_watch(db, watch_id))


@router.get("/{watch_id}/digest", response_model=Page[PublicDigestEntryOut])
async def list_public_digest(
    watch_id: uuid.UUID,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[PublicDigestEntryOut]:
    entries, total = await agent.list_public_digest(db, watch_id, limit=limit, offset=offset)
    return Page(
        items=[PublicDigestEntryOut.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )

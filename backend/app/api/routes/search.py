from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.schemas.common import ErrorResponse
from app.schemas.search import SearchDocument, SearchFacets, SearchHit, SearchIn, SearchOut
from app.services import retrieval
from app.services.retrieval import SearchFilters, SearchRequest

router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "",
    response_model=SearchOut,
    summary="Search passages across your library (keyword, semantic or hybrid)",
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def search(
    body: SearchIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> SearchOut:
    outcome = await retrieval.search(
        db,
        settings,
        user.id,
        SearchRequest(
            query=body.query,
            mode=body.mode,
            filters=SearchFilters(**body.filters.model_dump()),
            limit=body.limit,
            candidates=body.candidates,
            rerank=body.rerank,
            rerank_candidates=body.rerank_candidates,
            debug=body.debug,
        ),
    )
    return SearchOut(
        query=outcome.query,
        mode=outcome.mode,
        status=outcome.status,
        retrievers=outcome.retrievers,
        reranker=outcome.reranker,
        searched_papers=outcome.searched_papers,
        warnings=outcome.warnings,
        timings_ms=outcome.timings_ms,
        trace=outcome.trace,
        results=[
            SearchHit(
                rank=r.rank,
                chunk_id=r.chunk.id,
                document=SearchDocument(
                    id=r.document.id,
                    title=r.document.title,
                    authors_display=r.document.authors_display,
                    year=r.document.year,
                    doc_type=r.document.doc_type,
                    venue=r.metadata.venue if r.metadata else None,
                ),
                text=r.chunk.text,
                kind=r.chunk.kind,
                section_title=r.chunk.section_title,
                section_kind=r.chunk.section_kind,
                page_start=r.chunk.page_start,
                page_end=r.chunk.page_end,
                char_start=r.chunk.char_start,
                boxes=r.chunk.boxes,
                score=round(r.score, 6),
                score_kind=r.score_kind,
                matched_by=r.matched_by,
                retriever_ranks=r.retriever_ranks,
                fused_rank=r.fused_rank,
                highlights=r.highlights,
                snippet=r.snippet,
            )
            for r in outcome.results
        ],
    )


@router.get("/facets", response_model=SearchFacets, summary="Filter options for your library")
async def search_facets(user: CurrentUser, db: DbSession) -> SearchFacets:
    return SearchFacets.model_validate(await retrieval.facets(db, user.id))

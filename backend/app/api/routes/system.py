"""Health, readiness, metrics and public configuration."""

from __future__ import annotations

import hmac
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import __version__
from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.core.database import ping_database
from app.core.errors import AuthenticationError
from app.core.metrics import metrics
from app.core.redis import get_redis
from app.schemas.system import (
    ComponentStatus,
    HealthResponse,
    PublicConfigResponse,
    ReadinessResponse,
)
from app.services.llm import DEFAULT_MODELS, llm_status
from app.services.models.manager import model_manager, resolve_device
from app.services.usage import usage_prometheus

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """The process is up. Does not touch dependencies (use /ready for that)."""
    return HealthResponse(status="ok", version=__version__)


async def _probe(name: str, check: Callable[[], Awaitable[object]]) -> ComponentStatus:
    started = time.perf_counter()
    try:
        await check()
    except Exception as exc:  # report, never raise, from a probe
        return ComponentStatus(name=name, status="down", detail=type(exc).__name__)
    latency = round((time.perf_counter() - started) * 1000, 2)
    return ComponentStatus(name=name, status="ok", latency_ms=latency)


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready(settings: SettingsDep, response: Response) -> ReadinessResponse:
    components = [await _probe("database", ping_database)]
    redis = get_redis(settings)
    if redis is None:
        components.append(ComponentStatus(name="redis", status="disabled", detail="not configured"))
    else:
        components.append(await _probe("redis", redis.ping))

    is_ready = all(c.status in ("ok", "disabled") for c in components)
    if not is_ready:
        response.status_code = 503
    return ReadinessResponse(status="ready" if is_ready else "not_ready", components=components)


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def prometheus_metrics(request: Request, db: DbSession, settings: SettingsDep) -> str:
    if settings.metrics_token is not None:
        expected = f"Bearer {settings.metrics_token.get_secret_value()}"
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise AuthenticationError("A metrics token is required.")
    # This process's series, plus language-model usage from the database (all processes).
    return metrics.render_prometheus() + await usage_prometheus(db)


@router.get("/api/v1/metrics/summary", summary="Metrics snapshot (JSON) for the diagnostics UI")
async def metrics_summary(_user: CurrentUser) -> JSONResponse:
    return JSONResponse(metrics.snapshot())


@router.get("/api/v1/config", response_model=PublicConfigResponse, summary="Public configuration")
async def public_config(settings: SettingsDep) -> PublicConfigResponse:
    return PublicConfigResponse(
        app_name=settings.app_name,
        environment=settings.environment.value,
        allow_registration=settings.allow_registration,
        max_upload_size_mb=settings.max_upload_size_mb,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, ""),
        embedding_model=settings.embedding_model,
        reranker_model=settings.reranker_model,
        local_only=settings.local_only,
        free_tier=settings.free_tier,
        download_url=settings.download_url,
        demo_mode=settings.demo_mode,
        uploads_enabled=settings.uploads_enabled if not settings.demo_mode else False,
        github_url=settings.github_url,
    )


@router.get("/api/v1/ai/status", summary="AI pipeline configuration and loaded models")
async def ai_status(_user: CurrentUser, settings: SettingsDep) -> JSONResponse:
    """What the retrieval stack is running on — no secrets, no model loading."""
    return JSONResponse(
        {
            "embedding": {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model
                if settings.embedding_provider != "hashing"
                else f"hashing-v1-{settings.embedding_dimension or 384}",
                "remote": settings.embedding_provider == "openai",
                "device": resolve_device(settings.model_device),
            },
            "chunking": {
                "strategy": settings.chunking_strategy,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "contextual_headers": settings.contextual_chunk_headers,
            },
            "reranker": {
                "provider": settings.reranker_provider,
                "model": None if settings.reranker_provider == "none" else settings.reranker_model,
                "remote": settings.reranker_provider == "api",
                "candidates": settings.rerank_candidates,
            },
            "retrieval": {
                "sparse": settings.sparse_retriever,
                "candidates_per_retriever": settings.top_k,
                "rrf_k": settings.rrf_k,
            },
            "vector_store": {
                "backend": settings.vector_store,
                "mode": "server" if settings.qdrant_url else "embedded",
            },
            "llm": await llm_status(settings),
            "verifier": {
                "provider": settings.verifier_provider,
                "model": settings.verifier_model if settings.verifier_provider == "nli" else None,
            },
            "context": {
                "token_budget": settings.context_token_budget,
                "max_passages": settings.context_max_passages,
                "min_relevance": settings.context_min_relevance,
            },
            "loaded_models": model_manager.status(),
            "local_only": settings.local_only,
        }
    )

"""Usage and performance: language-model tokens and cost per feature, and latency per stage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.core.cache import cache_stats
from app.core.metrics import metrics
from app.services.llm import current_model
from app.services.usage import usage_summary

router = APIRouter(prefix="/usage", tags=["usage"])

# Histograms shown as stages on the performance panel, in pipeline order.
STAGES = (
    ("search_latency_ms", "Search (total)"),
    ("rerank_latency_ms", "Reranking"),
    ("llm_latency_ms", "Language model call"),
    ("chat_latency_ms", "Chat answer (total)"),
    ("summary_latency_ms", "Paper summary"),
    ("comparison_latency_ms", "Paper comparison"),
    ("http_request_duration_ms", "API request"),
)


@router.get("", summary="Your language-model usage: tokens, cost and latency")
async def get_usage(
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    model = current_model(settings)
    return await usage_summary(db, settings, user.id, days, model)


@router.get("/performance", summary="Latency per stage and cache hit rates (this server process)")
async def get_performance(user: CurrentUser) -> dict[str, Any]:
    del user  # any signed-in user; these are process-wide aggregates, no one's data
    stages = []
    for name, label in STAGES:
        merged = metrics.histogram_summary(name)
        if merged is not None:
            stages.append({"key": name, "label": label, **merged})
    return {"stages": stages, "caches": cache_stats(), "since": metrics.started_at}

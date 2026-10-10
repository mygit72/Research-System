from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down", "disabled"]
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    components: list[ComponentStatus]


class PublicConfigResponse(BaseModel):
    """Non-secret configuration the frontend may display (never API keys)."""

    app_name: str
    environment: str
    allow_registration: bool
    max_upload_size_mb: int
    llm_provider: str
    llm_model: str
    embedding_model: str
    reranker_model: str
    local_only: bool
    free_tier: bool  # the server's model is a shared free one that users opt in to
    download_url: str  # where to get the code to run your own copy ("" when not published)

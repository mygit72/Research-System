"""Application configuration.

All settings are read from environment variables (or a `.env` file). Nothing
secret is ever hard-coded; defaults are chosen so the app runs locally without
Docker (SQLite + embedded services) and in production via docker compose.
"""

from __future__ import annotations

import json
import os
import uuid
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _env_files() -> tuple[Path, ...]:
    """The `.env` files settings are read from. NO_ENV_FILE=1 (the test suite, the end-to-end
    server) means none: only real environment variables count, so a developer's own `.env` —
    their model, their API key — can't change what a test does or be used by one."""
    if os.environ.get("NO_ENV_FILE"):
        return ()
    return (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class JobBackend(StrEnum):
    """How background jobs are executed.

    `inline` runs jobs as asyncio tasks inside the API process (no broker needed),
    `celery` dispatches them to Celery workers via Redis.
    """

    INLINE = "inline"
    CELERY = "celery"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App -----------------------------------------------------------------
    app_name: str = "Research Intelligence"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_prefix: str = "/api/v1"
    # NoDecode: accept "a,b" from env vars instead of requiring a JSON list.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: str = "INFO"
    log_json: bool = False

    # --- Storage ---------------------------------------------------------------
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_ROOT / 'data' / 'app.db').as_posix()}"
    database_echo: bool = False
    redis_url: str | None = None
    qdrant_url: str | None = None  # None -> embedded local Qdrant (added in Phase 3)
    vector_store: str = "qdrant"  # qdrant | pgvector
    storage_dir: Path = BACKEND_ROOT / "data" / "files"

    # --- Auth ----------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-insecure-change-me-dev-insecure-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    allow_registration: bool = True

    # --- Rate limiting -----------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    # --- Jobs ----------------------------------------------------------------
    job_backend: JobBackend = JobBackend.INLINE
    inline_job_concurrency: int = 1  # conservative concurrency for free-tier memory constraints

    # The code runner is a separate internal service. It launches disposable containers; the
    # API never executes a project's Python files in its own process.
    project_runner_url: str | None = None
    project_runner_token: SecretStr | None = None

    # --- Uploads -----------------------------------------------------------------
    max_upload_size_mb: int = 50
    max_zip_size_mb: int = 200  # a folder of papers as one .zip

    # --- AI (consumed from Phase 2 onward; declared now so config is one place) --
    llm_provider: str = "ollama"  # ollama | openai (any compatible API) | fake (tests)
    llm_model: str = ""  # empty = provider default (ollama: qwen2.5:3b)
    ollama_base_url: str = "http://localhost:11434"
    code_llm_model: str = ""  # optional local Ollama model for software/code requests
    openai_api_key: SecretStr | None = None
    llm_api_base: str = "https://api.openai.com/v1"
    llm_timeout: float = 300.0
    llm_max_tokens: int = 700  # answer length cap
    code_llm_context_window: int = 8192  # larger Ollama context for complete code drafts
    llm_temperature: float = 0.1
    # Cost accounting (USD per million tokens). Local models cost nothing per token; set these
    # for a hosted provider to see cost in the evaluation dashboard.
    llm_price_input_per_million: float = 0.0
    llm_price_output_per_million: float = 0.0
    # Per-model prices, overriding the two above: LLM_PRICES='{"gpt-4.1-mini": [0.4, 1.6]}'
    # (input, output; USD per million tokens). The cost of each call is stored when it's made.
    llm_prices: dict[str, tuple[float, float]] = Field(default_factory=dict)
    # --- Answering (Phase 6) ---
    context_token_budget: int = 2500  # evidence tokens sent to the model
    context_max_passages: int = 8
    context_min_relevance: float = 0.02  # reranker score below which a passage is dropped
    chat_history_turns: int = 3  # previous exchanges included for follow-up questions
    verifier_provider: str = "nli"  # nli (cross-encoder entailment) | lexical | none
    verifier_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    # --- Paper summaries (Phase 7) ---
    summary_auto: bool = True  # summarize each paper after indexing, if the model is ready
    summary_context_tokens: int = 1400  # evidence tokens per section group (one model call)
    summary_max_passages: int = 6  # per section group
    summary_max_tokens: int = 450  # output cap per section group
    embedding_provider: str = "sentence_transformers"  # sentence_transformers | hashing | openai
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 0  # 0 = model default (needed for remote/hashing providers)
    embedding_batch_size: int = 32
    embedding_api_key: SecretStr | None = None
    embedding_api_base: str = "https://api.openai.com/v1"
    reranker_provider: str = "cross_encoder"  # cross_encoder | api | lexical (tests) | none
    # Fast on CPU (~0.8 s for 30 passages here); BAAI/bge-reranker-base is more accurate but
    # ~8x slower on CPU, so it's the recommended choice with a GPU.
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_api_key: SecretStr | None = None
    reranker_api_base: str = "https://api.jina.ai/v1"  # any /rerank API (Jina, Cohere v2, ...)
    reranker_batch_size: int = 16
    reranker_max_length: int = 512  # tokens per (query, passage) pair
    model_device: str = "auto"  # auto | cpu | cuda | mps
    model_dtype: str = "auto"  # auto | float32 | float16
    max_loaded_models: int = 4  # embedder + reranker + NLI verifier (+1 spare); LRU beyond
    model_idle_unload_seconds: int = 900
    ocr_enabled: bool = True
    # fixed | recursive | sentence | section_aware | semantic
    chunking_strategy: str = "section_aware"
    chunk_size: int = 384  # tokens of the embedding model (BGE truncates at 512)
    chunk_overlap: int = 64
    contextual_chunk_headers: bool = True
    top_k: int = 50  # candidates taken from each retriever before fusion
    rerank_candidates: int = 30  # fused passages rescored by the reranker
    rerank_top_k: int = 10  # passages kept after reranking for answer context (Phase 6)
    rrf_k: int = 60
    sparse_retriever: str = "bm25"  # bm25 (own implementation) | postgres (PostgreSQL FTS)
    warm_models_on_startup: bool = True  # load the embedding model at startup, not first search
    bm25_k1: float = 1.2  # term-frequency saturation
    bm25_b: float = 0.75  # document-length normalization
    cache_enabled: bool = True
    # Answers one user may have streaming at once (each keeps the model busy).
    chat_max_concurrent_per_user: int = 2
    # When set, GET /metrics requires "Authorization: Bearer <token>" (Prometheus: authorization
    # credentials). Leave unset only when /metrics isn't reachable from outside.
    metrics_token: SecretStr | None = None
    # Inline jobs interrupted by a restart are resumed on startup (see workers/recovery.py).
    resume_jobs_on_startup: bool = True
    # Semantic answer cache (Phase 14): reuse an earlier answer written from the same passages
    # for a near-identical first question. See services/rag/answer_cache.py for the guards.
    answer_cache_enabled: bool = True
    answer_cache_min_similarity: float = 0.95
    answer_cache_days: int = 30
    local_only: bool = False  # when true, remote AI providers are refused
    hf_hub_offline: bool = False  # use only already-cached Hugging Face models
    # --- Research watches: autonomous arXiv monitoring ---
    agent_scheduler_enabled: bool = True
    agent_scheduler_poll_seconds: int = 300
    agent_watch_min_interval_hours: int = 6
    agent_watch_default_interval_hours: int = 24
    agent_watch_lookback_days: int = 14
    agent_watch_max_results_per_run: int = 10
    agent_watch_default_relevance_threshold: float = 0.35
    agent_watch_max_active_per_user: int = 10
    # A watch's run writes a full literature review once it keeps at least this many
    # candidates (opt-in per watch via `synthesize`); capped at this many papers even if more
    # were kept, to bound one scheduled tick's latency and cost.
    agent_watch_synthesis_min_papers: int = 3
    agent_watch_synthesis_max_papers: int = 8
    # Used to build an absolute link in Slack/Discord messages; empty = omit the link rather
    # than send a broken one.
    app_base_url: str = ""
    # --- Each user's own model (Settings -> AI) ---
    # Users may bring their own API key for a hosted provider (OpenAI, Gemini, Groq, OpenRouter,
    # Mistral). Their AI work then runs on, and is billed to, their key.
    allow_user_api_keys: bool = True
    # Users may point at a model on a private network: Ollama on this machine, LM Studio, any
    # OpenAI-compatible URL. Unset = allowed except in production, because a public server must
    # not reach into its own network on a user's behalf. Set true for a self-hosted install.
    allow_local_models: bool | None = None
    # Encrypts the API keys users save. Unset = a key derived from JWT_SECRET. Changing it (or
    # JWT_SECRET while it's unset) makes saved keys unreadable: users are asked to re-enter them.
    model_key_secret: SecretStr | None = None
    # --- The shared free model (a public site) ---
    # FREE_TIER=true says the server's model above (LLM_PROVIDER / LLM_MODEL) is a free,
    # rate-limited hosted model that every user reaches through the server's one key, e.g.
    # NVIDIA Nemotron 3 Ultra on OpenRouter. Then nobody's text is sent to it until they choose
    # it in Settings → AI (it leaves the server for a third party), calls are paced so the key's
    # limit isn't hit, each user has a daily allowance, and papers aren't summarized on upload.
    free_tier: bool = False
    free_tier_label: str = ""  # shown to users; empty = the model's name
    free_tier_host: str = ""  # who receives the text, shown to users: "NVIDIA, through OpenRouter"
    free_tier_requests_per_minute: int = 18  # all users together; keep under the key's own limit
    free_tier_requests_per_day: int = 0  # all users together; 0 = the key has no daily limit
    free_tier_daily_requests_per_user: int = 50
    free_tier_max_wait_seconds: int = 120  # how long a call may queue before "busy, try again"
    # Extra fields for the server's OpenAI-compatible model, merged into every request:
    # LLM_EXTRA_BODY='{"reasoning": {"enabled": false}}' turns off a reasoning model's thinking
    # on OpenRouter (needed for Nemotron 3 Ultra: see DEPLOYMENT.md).
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)
    # Where people can get the code to run their own copy; shown in Settings and Help when set.
    download_url: str = ""
    # Public demo settings (locks down uploads, shares synthetic library, protects demo data)
    demo_mode: bool = False
    demo_user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
    uploads_enabled: bool = True
    github_url: str = "https://github.com/mygit72/Research-System"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _ensure_asyncpg_scheme(cls, value: str) -> str:
        """Auto-transform bare ``postgresql://`` to ``postgresql+asyncpg://``.

        Neon CLI writes ``postgresql://…`` with parameters like ``sslmode=require``
        and ``channel_binding=require``. SQLAlchemy's asyncpg driver needs:
        1. ``+asyncpg`` in the URL scheme
        2. Removal of asyncpg-unsupported query parameters such as ``channel_binding``
        and ``sslmode`` (asyncpg uses ssl kwarg / parameter rather than libpq sslmode).
        """
        if value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value[len("postgresql://"):]
        
        if "+asyncpg" in value and "?" in value:
            from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

            parsed = urlparse(value)
            # Filter out parameters that asyncpg's connect() does not accept as kwargs
            unsupported = {"channel_binding", "sslmode"}
            query_params = [
                (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k.lower() not in unsupported
            ]
            # asyncpg accepts ssl=require directly in query params or defaults to ssl if ssl=true/require
            # Keep any remaining valid parameters
            new_query = urlencode(query_params)
            value = urlunparse(parsed._replace(query=new_query))
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def local_models_allowed(self) -> bool:
        if self.allow_local_models is not None:
            return self.allow_local_models
        return not self.is_production

    def validate_for_production(self) -> None:
        """Fail fast on insecure configuration in production."""
        if not self.is_production:
            return
        if "dev-insecure" in self.jwt_secret.get_secret_value():
            raise RuntimeError("JWT_SECRET must be set to a strong random value in production")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")
        if self.project_runner_url:
            runner_token = (
                self.project_runner_token.get_secret_value()
                if self.project_runner_token
                else ""
            )
            if (
                len(runner_token) < 32
                or runner_token == "local-development-runner-token-change-me"
            ):
                raise RuntimeError(
                    "Set PROJECT_RUNNER_TOKEN to a long random value before enabling the "
                    "project runner in production"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()

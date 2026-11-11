"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router, assets_router
from app.api.routes import system
from app.core.config import Environment, JobBackend, Settings, get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.services.embeddings import get_embedding_provider
from app.services.models.manager import model_manager
from app.services.rag.pipeline import get_verifier
from app.services.reranking import get_reranker
from app.services.vectorstore import close_vector_store
from app.workers import handlers  # noqa: F401  (registers job handlers)
from app.workers.dispatcher import get_dispatcher
from app.workers.recovery import recover_interrupted_jobs
from app.workers.scheduler import run_scheduler

log = get_logger(__name__)


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    hint: str | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "code": code,
        "message": message,
        "hint": hint,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details:
        body["details"] = details
    headers = {}
    if details and "retry_after" in details:
        headers["Retry-After"] = str(details["retry_after"])
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request, exc.status_code, exc.code, exc.message, exc.hint, exc.details or None
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"] if p != "body"),
                "message": str(err["msg"]).removeprefix("Value error, "),
            }
            for err in exc.errors()
        ]
        message = fields[0]["message"] if len(fields) == 1 else "Some fields are invalid."
        return _error_response(
            request, 422, "validation_error", message, details={"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return _error_response(
            request,
            500,
            "internal_error",
            "Something went wrong on our side.",
            hint="Please try again. If it keeps happening, share the request ID with support.",
        )


def _warm_models(settings: Settings) -> None:
    try:
        get_embedding_provider(settings).embed_query("warm up")
        reranker = get_reranker(settings)
        if reranker is not None and not reranker.is_remote:
            reranker.score("warm up", ["warm up"])
        verifier = get_verifier(settings)  # otherwise the first chat answer waits for it
        if verifier is not None:
            verifier.entailment([("warm up", "warm up")])
        log.info(
            "models_warmed",
            embedding=settings.embedding_model,
            reranker=settings.reranker_model,
            verifier=verifier.name if verifier else None,
        )
    except Exception as exc:  # search reports the problem properly when it's used
        log.warning("model_warmup_failed", error=repr(exc))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.hf_hub_offline:
        # Set before lazy imports of sentence-transformers/transformers in the warmup task.
        os.environ["HF_HUB_OFFLINE"] = "1"
    settings.validate_for_production()
    configure_logging(settings.log_level, settings.log_json)
    model_manager.max_loaded = settings.max_loaded_models
    model_manager.idle_seconds = settings.model_idle_unload_seconds

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        init_engine(settings)
        log.info("startup", version=__version__, environment=settings.environment.value)
        warmup = None
        if settings.warm_models_on_startup and settings.environment != Environment.TEST:
            # Load the embedding model in the background so the first search isn't slow.
            warmup = asyncio.create_task(asyncio.to_thread(_warm_models, settings))
        if settings.demo_mode and settings.environment != Environment.TEST:
            from app.demo.shared_library import ensure_shared_sample_library

            try:
                await ensure_shared_sample_library(settings, get_session_factory())
            except Exception as exc:
                log.warning("demo_bootstrap_failed", error=str(exc))
        if settings.job_backend == JobBackend.INLINE and settings.resume_jobs_on_startup:
            # Jobs that were running when the process stopped resume (or are failed cleanly).
            await recover_interrupted_jobs(get_session_factory(), get_dispatcher(settings))
        scheduler_task = None
        if settings.agent_scheduler_enabled and settings.environment != Environment.TEST:
            scheduler_task = asyncio.create_task(run_scheduler(settings))
        yield
        if scheduler_task is not None and not scheduler_task.done():
            scheduler_task.cancel()
        if warmup is not None and not warmup.done():
            warmup.cancel()
        try:
            await asyncio.wait_for(get_dispatcher(settings).drain(), timeout=10)
        except TimeoutError:
            log.warning("shutdown_jobs_still_running")
        await close_redis()
        close_vector_store()
        await dispose_engine()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="Ingest, search, compare and chat with research papers — with citations.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "retry-after"],
    )
    app.add_middleware(RequestContextMiddleware)
    _install_exception_handlers(app)
    app.include_router(system.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(assets_router, prefix=settings.api_prefix)
    return app


app = create_app()

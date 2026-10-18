from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.api.routes import (
    assets,
    auth,
    chat,
    comparisons,
    demo,
    documents,
    evaluation,
    jobs,
    knowledge,
    model_choice,
    notifications,
    organization,
    projects,
    public,
    reports,
    search,
    summaries,
    usage,
    users,
    watches,
    webhooks,
)

api_router = APIRouter(dependencies=[Depends(rate_limit("api"))])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(model_choice.router)
api_router.include_router(webhooks.router)
api_router.include_router(jobs.router)
api_router.include_router(documents.router)
api_router.include_router(search.router)
api_router.include_router(chat.router)
api_router.include_router(summaries.router)
api_router.include_router(comparisons.router)
api_router.include_router(organization.router)
api_router.include_router(knowledge.router)
api_router.include_router(reports.router)
api_router.include_router(projects.router)
api_router.include_router(watches.router)
api_router.include_router(public.router)
api_router.include_router(notifications.router)
api_router.include_router(evaluation.router)
api_router.include_router(usage.router)
api_router.include_router(demo.router)

# Signed assets: many small requests while scrolling a paper; not rate-limited
# like the API (the signature already bounds who can call them).
assets_router = APIRouter()
assets_router.include_router(assets.router)

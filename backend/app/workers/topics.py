"""`topics.name` job: ask the language model for readable topic names.

Clusters already carry names made from their top terms, so a missing or failing model
only leaves those in place (naming_status "fallback", with the reason).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.models.document import Document
from app.models.knowledge import TopicClustering
from app.services.knowledge.topics import NAMING_JOB, clean_name, grounded, naming_prompt
from app.services.llm import GenerationParams, LLMError, Message, get_llm, llm_status
from app.services.summaries.engine import complete
from app.workers.registry import JobContext, job_handler, on_interrupted


async def _finish(
    ctx: JobContext,
    run_id: uuid.UUID,
    status: str,
    names: dict[int, str] | None = None,
    model: str | None = None,
    error: str | None = None,
) -> None:
    async with ctx.session_factory() as session:
        run = await session.get(TopicClustering, run_id)
        if run is None:
            return
        clusters = []
        for cluster in run.result.get("clusters", []):
            if names and cluster["id"] in names:
                cluster = {**cluster, "name": names[cluster["id"]], "name_source": "model"}
            clusters.append(cluster)
        run.result = {**run.result, "clusters": clusters}  # reassign: JSON isn't mutation-tracked
        run.naming_status = status
        run.naming_model = model
        run.error_message = error
        await session.commit()


@on_interrupted(NAMING_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _finish(ctx, uuid.UUID(ctx.payload["clustering_id"]), "failed", error=message)


@job_handler(NAMING_JOB)
async def name_topics(ctx: JobContext) -> dict[str, Any]:
    run_id = uuid.UUID(ctx.payload["clustering_id"])
    settings = get_settings()
    async with ctx.session_factory() as session:
        run = await session.get(TopicClustering, run_id)
        if run is None:
            return {"status": "deleted"}
        clusters = run.result.get("clusters", [])
        ids = [uuid.UUID(d) for c in clusters for d in c["document_ids"]]
        titles = {
            str(doc_id): title
            for doc_id, title in (
                await session.execute(
                    select(Document.id, Document.title).where(Document.id.in_(ids))
                )
            ).all()
        }
    status = await llm_status(settings)
    if not status.get("ready"):
        message = status.get("problem") or "The language model isn't ready."
        await _finish(ctx, run_id, "fallback", error=f"Named from top terms: {message}")
        return {"status": "fallback", "reason": message}
    llm = get_llm(settings)
    names: dict[int, str] = {}
    replies: dict[int, str] = {}
    model = status.get("model")
    for index, cluster in enumerate(clusters):
        await ctx.report(
            "naming", index / len(clusters), f"Naming topic {index + 1} of {len(clusters)}"
        )
        try:
            result = await complete(
                llm,
                [Message("user", naming_prompt(cluster, titles))],
                GenerationParams(max_tokens=24, temperature=0.2),
            )
        except LLMError as exc:
            await _finish(
                ctx, run_id, "fallback", error=f"Named from top terms: {exc.user_message}"
            )
            return {"status": "fallback", "reason": exc.user_message}
        model = result.model or model
        replies[cluster["id"]] = result.text[:200]
        name = clean_name(result.text)
        if name and grounded(name, cluster, clusters, titles):
            names[cluster["id"]] = name
    rejected = len(clusters) - len(names)
    if not names:
        await _finish(
            ctx,
            run_id,
            "fallback",
            model=model,
            error="Named from top terms: the model's names didn't match their topics.",
        )
        return {"status": "fallback", "replies": replies}
    note = None
    if rejected:
        names_word = "name" if rejected == 1 else "names"
        note = f"{rejected} AI {names_word} didn't fit the topic; those keep their top-terms name."
    await _finish(ctx, run_id, "done", names, model, error=note)
    return {"status": "done", "named": len(names), "of": len(clusters), "replies": replies}

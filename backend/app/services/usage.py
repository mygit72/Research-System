"""Language-model usage: tokens, latency and cost of every call, by user and feature.

Every provider returned by `get_llm` is wrapped in `MeteredLLM`. The wrapper doesn't know
who is asking; that comes from `usage_scope(...)`, a context variable set by the job runner
(feature from the job kind) and by chat. Each call is then:

- counted in the process metrics (Prometheus: tokens, cost, latency by feature and model),
- stored as an `llm_usage` row, priced with the table in effect at the time.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.core.metrics import format_labels, metrics
from app.models.usage import LLMUsage
from app.services.llm.base import (
    GenerationParams,
    LLMProvider,
    Message,
    StreamEvent,
    count_tokens,
)

log = get_logger(__name__)

# Job kind → feature shown on the usage page.
JOB_FEATURES = {
    "paper.summarize": "summary",
    "comparison.generate": "comparison",
    "report.generate": "report",
    "project.suggest": "project",
    "topics.name": "topics",
    "eval.run": "evaluation",
    "eval.generate": "evaluation",
    "agent.run_watch": "watch",
}


@dataclass(frozen=True, slots=True)
class UsageScope:
    user_id: uuid.UUID | None
    feature: str
    job_id: uuid.UUID | None = None


_scope: ContextVar[UsageScope | None] = ContextVar("llm_usage_scope", default=None)


@contextmanager
def usage_scope(
    user_id: uuid.UUID | None, feature: str, job_id: uuid.UUID | None = None
) -> Iterator[UsageScope]:
    scope = UsageScope(user_id, feature, job_id)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


def prices(settings: Settings, model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens for this model."""
    if model in settings.llm_prices:
        return settings.llm_prices[model]
    return settings.llm_price_input_per_million, settings.llm_price_output_per_million


def cost_usd(settings: Settings, model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = prices(settings, model)
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


class MeteredLLM:
    """Same interface as the wrapped provider; records each call when its stream ends."""

    def __init__(
        self, inner: LLMProvider, settings: Settings, scope: UsageScope | None = None
    ) -> None:
        self.inner = inner
        self.settings = settings
        self.scope = scope
        self.name = inner.name
        self.model_id = inner.model_id
        self.is_remote = inner.is_remote

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        first_token: float | None = None
        parts: list[str] = []
        final: StreamEvent | None = None
        status = "stopped"  # the consumer closed the stream before the end
        try:
            async for event in self.inner.stream(messages, params):
                if event.text:
                    if first_token is None:
                        first_token = time.perf_counter()
                    parts.append(event.text)
                if event.done:
                    final = event
                    status = "ok"
                yield event
        except Exception as exc:
            # A call refused before anything was sent (a used-up allowance) isn't a call.
            status = "error" if getattr(exc, "sent", True) else "refused"
            raise
        finally:
            if status != "refused":
                await self._record(messages, parts, final, status, started, first_token)

    async def _record(
        self,
        messages: list[Message],
        parts: list[str],
        final: StreamEvent | None,
        status: str,
        started: float,
        first_token: float | None,
    ) -> None:
        scope = self.scope or _scope.get() or UsageScope(None, "other")
        model = (final.model if final and final.model else None) or self.model_id
        input_tokens = final.usage.input_tokens if final else 0
        output_tokens = final.usage.output_tokens if final else 0
        estimated = not (input_tokens or output_tokens)
        if estimated:  # stopped early, failed, or the provider reports no usage
            input_tokens = sum(count_tokens(m.content) for m in messages)
            output_tokens = count_tokens("".join(parts)) if parts else 0
        latency = round((time.perf_counter() - started) * 1000, 1)
        cost = cost_usd(self.settings, model, input_tokens, output_tokens)
        feature = scope.feature
        metrics.inc("llm_calls_total", 1, status=status, feature=feature, model=model)
        for direction, count in (("input", input_tokens), ("output", output_tokens)):
            labels = {"direction": direction, "feature": feature, "model": model}
            metrics.inc("llm_tokens_total", count, **labels)
        metrics.inc("llm_cost_usd_total", cost, feature=feature, model=model)
        metrics.observe("llm_latency_ms", latency, feature=feature, model=model)
        row = LLMUsage(
            user_id=scope.user_id,
            feature=scope.feature,
            job_id=scope.job_id,
            provider=self.name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated=estimated,
            latency_ms=latency,
            first_token_ms=round((first_token - started) * 1000, 1) if first_token else None,
            cost_usd=cost,
            status=status,
        )
        try:
            async with get_session_factory()() as session:
                session.add(row)
                await session.commit()
        except Exception as exc:  # accounting must never break an answer
            log.warning("llm_usage_not_recorded", error=repr(exc))


# --- Prometheus ------------------------------------------------------------------------------


async def usage_prometheus(session: AsyncSession) -> str:
    """Usage counters from the `llm_usage` table, for every process.

    Jobs run in worker processes whose in-memory metrics the API can't see; the table has
    every call, so these series are complete. Counters only grow (rows are never updated),
    as Prometheus expects; they reset only if usage rows are deleted with an account.
    """
    rows = await session.execute(
        select(
            LLMUsage.feature,
            LLMUsage.model,
            LLMUsage.status,
            func.count(),
            func.sum(LLMUsage.input_tokens),
            func.sum(LLMUsage.output_tokens),
            func.sum(LLMUsage.cost_usd),
        ).group_by(LLMUsage.feature, LLMUsage.model, LLMUsage.status)
    )
    calls: list[str] = []
    tokens: list[str] = []
    cost: list[str] = []
    for feature, model, status, count, tokens_in, tokens_out, usd in rows.all():
        labels = (("feature", feature), ("model", model))
        calls.append(f"llm_usage_calls_total{format_labels((*labels, ('status', status)))} {count}")
        for direction, value in (("input", tokens_in), ("output", tokens_out)):
            series = format_labels((*labels, ("direction", direction)))
            tokens.append(f"llm_usage_tokens_total{series} {value or 0}")
        cost.append(f"llm_usage_cost_usd_total{format_labels(labels)} {round(usd or 0.0, 6)}")
    lines = [
        "# TYPE llm_usage_calls_total counter", *calls,
        "# TYPE llm_usage_tokens_total counter", *tokens,
        "# TYPE llm_usage_cost_usd_total counter", *cost,
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


# --- reading --------------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def _group(rows: list[LLMUsage], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[LLMUsage]] = {}
    for row in rows:
        groups.setdefault(str(getattr(row, key)), []).append(row)
    out = []
    for name, items in groups.items():
        latencies = [r.latency_ms for r in items if r.status == "ok"]
        first = [r.first_token_ms for r in items if r.first_token_ms is not None]
        out.append(
            {
                key: name,
                "calls": len(items),
                "errors": sum(1 for r in items if r.status == "error"),
                "input_tokens": sum(r.input_tokens for r in items),
                "output_tokens": sum(r.output_tokens for r in items),
                "cost_usd": round(sum(r.cost_usd for r in items), 6),
                "latency_p50_ms": percentile(latencies, 0.5),
                "latency_p95_ms": percentile(latencies, 0.95),
                "first_token_p50_ms": percentile(first, 0.5),
            }
        )
    return sorted(out, key=lambda g: -g["calls"])


async def usage_summary(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, days: int, current_model: str
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = list(
        (
            await session.execute(
                select(LLMUsage)
                .where(LLMUsage.user_id == user_id, LLMUsage.created_at >= since)
                .order_by(LLMUsage.created_at)
            )
        ).scalars()
    )
    by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = row.created_at.date().isoformat()
        entry = by_day.setdefault(
            day, {"day": day, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        entry["calls"] += 1
        entry["input_tokens"] += row.input_tokens
        entry["output_tokens"] += row.output_tokens
        entry["cost_usd"] = round(entry["cost_usd"] + row.cost_usd, 6)
    overall = {
        "calls": len(rows),
        "errors": sum(1 for r in rows if r.status == "error"),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "cost_usd": round(sum(r.cost_usd for r in rows), 6),
        "estimated_calls": sum(1 for r in rows if r.estimated),
        "latency_p50_ms": percentile([r.latency_ms for r in rows if r.status == "ok"], 0.5),
        "latency_p95_ms": percentile([r.latency_ms for r in rows if r.status == "ok"], 0.95),
    }
    price_in, price_out = prices(settings, current_model)
    return {
        "days": days,
        "totals": overall,
        "by_feature": _group(rows, "feature"),
        "by_model": _group(rows, "model"),
        "by_day": list(by_day.values()),
        "pricing": {
            "default": [
                settings.llm_price_input_per_million,
                settings.llm_price_output_per_million,
            ],
            "models": {k: list(v) for k, v in settings.llm_prices.items()},
            "current_model": {"model": current_model, "input": price_in, "output": price_out},
        },
    }

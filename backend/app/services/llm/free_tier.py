"""The site's shared free model (`FREE_TIER=true`).

A public site can offer every user a free hosted model through the server's one key, e.g.
NVIDIA Nemotron 3 Ultra on OpenRouter. Such keys are rate-limited for the whole site, so the
server's provider is wrapped here:

* **allowance** — each user gets `FREE_TIER_DAILY_REQUESTS_PER_USER` model calls a day (UTC),
  and the site as a whole `FREE_TIER_REQUESTS_PER_DAY` when the key has a daily limit. Counted
  from the `llm_usage` rows this provider writes (`provider = "free"`), so it holds across
  processes and restarts. One chat answer is one call; a summary is a few; a review is many.
* **pacing** — at most one call every `60 / FREE_TIER_REQUESTS_PER_MINUTE` seconds, for all
  users together. A call that finds the slot taken waits its turn (this is why the free model
  is slow when the site is busy) for up to `FREE_TIER_MAX_WAIT_SECONDS`, then fails with "busy".
  Shared between processes through Redis when it is configured, per process otherwise.
* **retries** — a 429 or 5xx before any text has arrived is retried twice, after the pause the
  service asked for.

It is used only by people who chose it in Settings → AI (see `llm/__init__.py`): their
questions and the passages needed to answer them leave this server for the model's host.
Nothing that identifies the user is sent with them.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import case, func, select

from app.core.config import Settings
from app.core.database import get_session_factory
from app.core.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.redis import get_redis
from app.models.usage import LLMUsage
from app.services.llm.base import GenerationParams, LLMError, LLMProvider, Message, StreamEvent
from app.services.llm.user_models import FREE

RETRIES = 2
OWN_MODEL_HINT = (
    "For no limits, use your own API key in Settings → AI, or run the app on your computer."
)
_local_pacer = InMemoryRateLimiter()


def describe(settings: Settings, model: str) -> dict[str, Any]:
    """What users are told about the free model before they choose it."""
    host = settings.free_tier_host
    if not host and settings.llm_provider == "openai":
        host = httpx.URL(settings.llm_api_base).host
    return {
        "label": settings.free_tier_label or model,
        "model": model,
        "host": host or settings.llm_provider,
        "daily_limit": settings.free_tier_daily_requests_per_user,
    }


# --- allowance ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Allowance:
    limit: int  # this user's calls per day
    used: int
    site_limit: int  # everyone's calls per day; 0 = no limit
    site_used: int
    resets_at: datetime  # the next midnight, UTC

    @property
    def remaining(self) -> int:
        left = self.limit - self.used
        if self.site_limit:
            left = min(left, self.site_limit - self.site_used)
        return max(0, left)

    @property
    def problem(self) -> str | None:
        if self.used >= self.limit:
            return f"You've used today's {self.limit} free requests."
        if self.site_limit and self.site_used >= self.site_limit:
            return "The free model has reached its limit for today (it is shared by everyone)."
        return None

    @property
    def hint(self) -> str:
        return f"It resets at {self.resets_at:%H:%M} UTC. {OWN_MODEL_HINT}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "daily_limit": self.limit,
            "used_today": self.used,
            "remaining_today": self.remaining,
            "resets_at": self.resets_at,
        }


async def allowance(settings: Settings, user_id: uuid.UUID) -> Allowance:
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session_factory()() as session:
        site_used, used = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(case((LLMUsage.user_id == user_id, 1), else_=0)), 0),
                ).where(LLMUsage.provider == FREE, LLMUsage.created_at >= midnight)
            )
        ).one()
    return Allowance(
        limit=settings.free_tier_daily_requests_per_user,
        used=int(used),
        site_limit=settings.free_tier_requests_per_day,
        site_used=int(site_used),
        resets_at=midnight + timedelta(days=1),
    )


# --- pacing -------------------------------------------------------------------------------------


def _pacer(settings: Settings) -> RateLimiter:
    redis = get_redis(settings)
    return RedisRateLimiter(redis) if redis is not None else _local_pacer


async def _wait_for_slot(settings: Settings, deadline: float) -> None:
    """Take the next free slot: one call per `60 / requests_per_minute` seconds, site-wide."""
    per_minute = settings.free_tier_requests_per_minute
    if per_minute <= 0:
        return
    window = max(1, math.ceil(60 / per_minute))
    pacer = _pacer(settings)
    while True:
        allowed, reset_in = await pacer.hit("free-tier", 1, window)
        if allowed:
            return
        if time.monotonic() + reset_in > deadline:
            raise LLMError(
                "The free model is busy: too many people are using it right now.",
                detail=f"Try again in a few minutes. {OWN_MODEL_HINT}",
                sent=False,
            )
        await asyncio.sleep(reset_in)


# --- the provider -------------------------------------------------------------------------------


class FreeTierLLM:
    """The server's model, shared: allowance checked, calls paced, busy answers retried."""

    name = FREE  # the `provider` of its llm_usage rows, which the allowance counts
    is_remote = True

    def __init__(self, inner: LLMProvider, settings: Settings, user_id: uuid.UUID) -> None:
        self.inner = inner
        self.settings = settings
        self.user_id = user_id
        self.model_id = inner.model_id

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        left = await allowance(self.settings, self.user_id)
        if left.problem:
            raise LLMError(left.problem, detail=left.hint, sent=False)
        deadline = time.monotonic() + self.settings.free_tier_max_wait_seconds
        attempt = 0
        while True:
            await _wait_for_slot(self.settings, deadline)
            started = False
            try:
                async for event in self.inner.stream(messages, params):
                    started = started or bool(event.text)
                    yield event
                return
            except LLMError as exc:
                attempt += 1
                pause = exc.retry_after if exc.retry_after is not None else 5.0 * attempt
                last = attempt > RETRIES or time.monotonic() + pause > deadline
                if started or not exc.busy:
                    raise
                if last:
                    raise LLMError(
                        "The free model is busy right now.",
                        detail=f"Try again in a few minutes. {OWN_MODEL_HINT}",
                        status=exc.status,
                    ) from exc
                await asyncio.sleep(pause)

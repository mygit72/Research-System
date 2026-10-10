"""Fixed-window rate limiting.

Uses Redis when configured (shared across API replicas) and falls back to an
in-process counter otherwise. Redis failures fail *open* and are logged: a
cache outage should degrade protection, not take the API down.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Record a request. Returns (allowed, seconds_until_reset)."""
        ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = defaultdict(int)

    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = int(time.time())
        window = now // window_seconds
        self._counts[(key, window)] += 1
        if len(self._counts) > 50_000:  # drop stale windows
            self._counts = defaultdict(
                int, {k: v for k, v in self._counts.items() if k[1] >= window}
            )
        reset_in = window_seconds - (now % window_seconds)
        return self._counts[(key, window)] <= limit, reset_in

    def reset(self) -> None:
        self._counts.clear()


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = int(time.time())
        window_key = f"ratelimit:{key}:{now // window_seconds}"
        reset_in = window_seconds - (now % window_seconds)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(window_key)
                pipe.expire(window_key, window_seconds + 1)
                count, _ = await pipe.execute()
        except RedisError as exc:
            log.warning("rate_limiter_unavailable", error=str(exc))
            return True, reset_in
        return int(count) <= limit, reset_in

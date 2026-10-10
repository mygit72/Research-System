from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings

_client: Redis | None = None


def get_redis(settings: Settings) -> Redis | None:
    """Shared Redis client, or None when Redis is not configured (local mode)."""
    global _client
    if settings.redis_url is None:
        return None
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None

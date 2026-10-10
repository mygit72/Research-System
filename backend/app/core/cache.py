"""Two-tier cache for expensive, deterministic results (query embeddings, reranker scores).

- Local tier: a bounded LRU in this process — always on, nanoseconds.
- Shared tier: Redis, when `REDIS_URL` is set — shared by the API and the workers and kept
  across restarts. A local miss checks Redis and fills the local tier from it.

Only results that are a pure function of their key are cached (same model + same text →
same vector or score), so entries never go stale and need no invalidation, only a TTL to
bound Redis memory. Redis errors are logged once and the cache keeps working locally: a
cache must never fail a search. `CACHE_ENABLED=false` turns caching off (for benchmarks).

The API is synchronous on purpose: callers run in worker threads next to the models.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import metrics

log = get_logger(__name__)

_redis: Any = None  # sync redis.Redis, created on first use
_redis_failed = False
_redis_lock = threading.Lock()


def _shared() -> Any:
    """The shared Redis client, or None (not configured, disabled, or failed before)."""
    global _redis, _redis_failed
    if _redis_failed:
        return None
    settings = get_settings()
    if not settings.cache_enabled or settings.redis_url is None:
        return None
    with _redis_lock:
        if _redis is None:
            import redis

            _redis = redis.Redis.from_url(
                settings.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5
            )
    return _redis


def _redis_error(exc: Exception) -> None:
    global _redis_failed
    if not _redis_failed:
        log.warning("cache_redis_unavailable", error=repr(exc))
    _redis_failed = True  # stay local for the life of the process


def digest(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


class NamedCache[V]:
    def __init__(
        self,
        name: str,
        max_entries: int,
        encode: Callable[[V], bytes],
        decode: Callable[[bytes], V],
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> None:
        self.name = name
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._encode, self._decode = encode, decode
        self._local: OrderedDict[str, V] = OrderedDict()
        self._lock = threading.Lock()
        self.stats = {"local_hits": 0, "shared_hits": 0, "misses": 0}
        _registry.setdefault(name, self)  # the app's instance; extra ones (tests) aren't listed

    def _count(self, kind: str, amount: int) -> None:
        if amount:
            self.stats[kind] += amount
            metrics.inc("cache_requests_total", amount, cache=self.name, result=kind)

    def get_many(self, keys: Sequence[str]) -> list[V | None]:
        if not get_settings().cache_enabled:
            return [None] * len(keys)
        found: list[V | None] = []
        with self._lock:
            for key in keys:
                value = self._local.get(key)
                if value is not None:
                    self._local.move_to_end(key)
                found.append(value)
        local_hits = sum(v is not None for v in found)
        missing = [i for i, v in enumerate(found) if v is None]
        shared_hits = 0
        client = _shared() if missing else None
        if client is not None:
            try:
                raw = client.mget([f"{self.name}:{keys[i]}" for i in missing])
            except Exception as exc:
                _redis_error(exc)
            else:
                fill = {}
                for i, blob in zip(missing, raw, strict=True):
                    if blob is not None:
                        found[i] = fill[keys[i]] = self._decode(blob)
                        shared_hits += 1
                self._store_local(fill)
        self._count("local_hits", local_hits)
        self._count("shared_hits", shared_hits)
        self._count("misses", len(keys) - local_hits - shared_hits)
        return found

    def get(self, key: str) -> V | None:
        return self.get_many([key])[0]

    def set_many(self, items: dict[str, V]) -> None:
        if not items or not get_settings().cache_enabled:
            return
        self._store_local(items)
        client = _shared()
        if client is not None:
            try:
                with client.pipeline(transaction=False) as pipe:
                    for key, value in items.items():
                        pipe.set(f"{self.name}:{key}", self._encode(value), ex=self.ttl_seconds)
                    pipe.execute()
            except Exception as exc:
                _redis_error(exc)

    def set(self, key: str, value: V) -> None:
        self.set_many({key: value})

    def _store_local(self, items: dict[str, V]) -> None:
        with self._lock:
            for key, value in items.items():
                self._local[key] = value
                self._local.move_to_end(key)
            while len(self._local) > self.max_entries:
                self._local.popitem(last=False)

    def __len__(self) -> int:
        return len(self._local)

    def clear(self) -> None:
        """Local tier only (tests, model changes); shared entries expire by TTL."""
        with self._lock:
            self._local.clear()


_registry: dict[str, NamedCache[Any]] = {}


def cache_stats() -> list[dict[str, Any]]:
    out = []
    for cache in _registry.values():
        hits = cache.stats["local_hits"] + cache.stats["shared_hits"]
        lookups = hits + cache.stats["misses"]
        out.append(
            {
                "name": cache.name,
                "entries": len(cache),
                "max_entries": cache.max_entries,
                **cache.stats,
                "hit_rate": round(hits / lookups, 3) if lookups else None,
                "shared": _shared() is not None,
            }
        )
    return out

"""Local model lifecycle: lazy loading, device/dtype selection, idle unloading.

Consumer hardware can't hold an embedder, a reranker and an LLM at once, so the
manager keeps at most `max_loaded` models and evicts the least recently used;
models idle longer than `idle_seconds` are released on the next access.
Thread-safe: embedding runs in worker threads.
"""

from __future__ import annotations

import gc
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def resolve_device(preference: str = "auto") -> str:
    if preference != "auto":
        return preference
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def resolve_dtype(preference: str, device: str) -> str:
    if preference != "auto":
        return preference
    return "float16" if device == "cuda" else "float32"


@dataclass
class _Entry:
    model: Any
    loaded_at: float
    last_used: float
    load_seconds: float


class ModelManager:
    def __init__(self, max_loaded: int = 2, idle_seconds: float = 900.0) -> None:
        self.max_loaded = max_loaded
        self.idle_seconds = idle_seconds
        self._models: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str, loader: Callable[[], Any]) -> Any:
        with self._lock:
            self._evict_idle()
            entry = self._models.get(key)
            if entry is None:
                started = time.perf_counter()
                model = loader()
                now = time.time()
                entry = _Entry(model, now, now, round(time.perf_counter() - started, 2))
                self._models[key] = entry
                log.info("model_loaded", model=key, seconds=entry.load_seconds)
                while len(self._models) > self.max_loaded:
                    evicted, _ = self._models.popitem(last=False)
                    log.info("model_unloaded", model=evicted, reason="capacity")
                    self._release()
            entry.last_used = time.time()
            self._models.move_to_end(key)
            return entry.model

    def _evict_idle(self) -> None:
        cutoff = time.time() - self.idle_seconds
        for key in [k for k, e in self._models.items() if e.last_used < cutoff]:
            del self._models[key]
            log.info("model_unloaded", model=key, reason="idle")
            self._release()

    def _release(self) -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "model": key,
                    "loaded_seconds_ago": round(time.time() - e.loaded_at),
                    "idle_seconds": round(time.time() - e.last_used),
                    "load_seconds": e.load_seconds,
                }
                for key, e in self._models.items()
            ]

    def unload_all(self) -> None:
        with self._lock:
            self._models.clear()
            self._release()


model_manager = ModelManager()

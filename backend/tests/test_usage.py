"""Usage and performance: every model call is metered by feature; caches and latency stages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core import cache as cache_module
from app.core.cache import NamedCache
from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.demo import sample_papers as sp
from app.services.llm import FakeLLM
from app.services.llm.base import GenerationParams, Message, StreamEvent, Usage
from app.services.summaries.engine import complete
from app.services.usage import MeteredLLM, cost_usd, usage_scope
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_chat_api import ask, new_conversation
from tests.test_indexing_api import upload

API = "/api/v1"


@pytest.fixture
async def lora(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> str:
    data = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return await upload(auth_client, settings, "l.pdf", data)


async def test_chat_and_jobs_are_metered_per_feature_and_priced(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, lora: str
) -> None:
    settings.llm_prices = {FakeLLM.model_id: (2.0, 10.0)}
    conversation = await new_conversation(auth_client)
    await ask(auth_client, conversation, "How much memory do low-rank adapters save?")
    response = await auth_client.post(f"{API}/documents/{lora}/summary")
    assert response.status_code == 202, response.text
    await get_dispatcher(settings).drain()

    usage = (await auth_client.get(f"{API}/usage", params={"days": 7})).json()
    features = {f["feature"]: f for f in usage["by_feature"]}
    assert set(features) == {"chat", "summary"}
    assert features["chat"]["calls"] == 1 and features["summary"]["calls"] >= 1
    chat = features["chat"]
    assert chat["input_tokens"] > 0 and chat["output_tokens"] > 0
    expected = (chat["input_tokens"] * 2.0 + chat["output_tokens"] * 10.0) / 1_000_000
    assert chat["cost_usd"] == pytest.approx(expected, abs=1e-5)
    totals = usage["totals"]
    assert totals["calls"] == sum(f["calls"] for f in usage["by_feature"])
    assert totals["estimated_calls"] == 0 and totals["latency_p50_ms"] is not None
    assert usage["by_model"][0]["model"] == FakeLLM.model_id
    assert usage["by_day"][0]["calls"] == totals["calls"]
    assert usage["pricing"]["current_model"] == {
        "model": FakeLLM.model_id,
        "input": 2.0,
        "output": 10.0,
    }

    # Usage is personal.
    owner = auth_client.headers["Authorization"]
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.get(f"{API}/usage")).json()["totals"]["calls"] == 0
    client.headers["Authorization"] = owner

    performance = (await auth_client.get(f"{API}/usage/performance")).json()
    stages = {s["key"]: s for s in performance["stages"]}
    assert {"search_latency_ms", "llm_latency_ms", "chat_latency_ms"} <= set(stages)
    assert stages["llm_latency_ms"]["count"] >= 2 and stages["llm_latency_ms"]["p50_ms"] >= 0
    names = {c["name"] for c in performance["caches"]}
    assert "query_embeddings" in names

    # Prometheus: usage from the database (jobs run in other processes), latency histograms.
    exposition = (await auth_client.get("/metrics")).text
    assert (
        f'llm_usage_calls_total{{feature="chat",model="{FakeLLM.model_id}",status="ok"}} 1'
        in exposition
    )
    assert 'llm_usage_tokens_total{feature="summary"' in exposition
    assert 'chat_latency_ms_bucket{le="300000"}' in exposition


class _Slow:
    """A provider that streams words and reports usage only at the end."""

    name, model_id, is_remote = "slow", "slow-1", False

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        for word in ["[1] [1] [1] "] * 30:  # loops on markers: `complete` stops it early
            yield StreamEvent(text=word)
        yield StreamEvent(done=True, usage=Usage(100, 50), model="slow-1")


async def test_a_stream_stopped_early_is_recorded_with_estimated_tokens(
    settings: Settings, auth_client: AsyncClient
) -> None:
    llm = MeteredLLM(_Slow(), settings)
    with usage_scope(None, "evaluation"):
        result = await complete(llm, [Message("user", "x" * 400)], GenerationParams())
    assert result.stopped_loop
    from sqlalchemy import select

    from app.core.database import get_session_factory
    from app.models.usage import LLMUsage

    async with get_session_factory()() as session:
        row = (await session.execute(select(LLMUsage))).scalars().one()
    assert (row.status, row.feature, row.estimated) == ("stopped", "evaluation", True)
    assert row.input_tokens == 100 and row.output_tokens > 0  # estimated from the text


def test_cost_uses_the_model_price_or_the_default(settings: Settings) -> None:
    settings.llm_price_input_per_million, settings.llm_price_output_per_million = 1.0, 2.0
    settings.llm_prices = {"big": (10.0, 40.0)}
    assert cost_usd(settings, "big", 1_000_000, 500_000) == 30.0
    assert cost_usd(settings, "other", 1_000_000, 500_000) == 2.0


def test_histogram_percentiles_interpolate_within_buckets() -> None:
    registry = MetricsRegistry()
    for value in [20] * 50 + [400] * 45 + [20_000] * 5:
        registry.observe("x_ms", value, kind="a" if value < 100 else "b")
    summary = registry.histogram_summary("x_ms")
    assert summary is not None and summary["count"] == 100
    assert 10 <= summary["p50_ms"] <= 25  # 50th value is in the (10, 25] bucket
    assert 250 <= summary["p95_ms"] <= 500
    assert registry.histogram_summary("missing") is None


class _FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.data: dict[str, bytes] = {}
        self.fail = fail

    def mget(self, keys: list[str]) -> list[bytes | None]:
        if self.fail:
            raise ConnectionError("redis down")
        return [self.data.get(k) for k in keys]

    def pipeline(self, transaction: bool = False) -> Any:
        store = self

        class Pipe:
            def __enter__(self) -> Pipe:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def set(self, key: str, value: bytes, ex: int) -> None:
                store.data[key] = value

            def execute(self) -> None:
                if store.fail:
                    raise ConnectionError("redis down")

        return Pipe()


def _floats() -> NamedCache[float]:
    return NamedCache("t", 2, encode=lambda v: str(v).encode(), decode=lambda b: float(b))


def test_two_tier_cache_shares_through_redis_and_survives_its_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = _FakeRedis()
    monkeypatch.setattr(cache_module, "_shared", lambda: shared)
    api, worker = _floats(), _floats()  # two processes, one Redis
    api.set_many({"a": 1.0, "b": 2.0})
    assert shared.data == {"t:a": b"1.0", "t:b": b"2.0"}
    assert worker.get_many(["a", "b", "c"]) == [1.0, 2.0, None]
    assert worker.stats == {"local_hits": 0, "shared_hits": 2, "misses": 1}
    assert worker.get("a") == 1.0 and worker.stats["local_hits"] == 1  # now local
    api.set("c", 3.0)  # LRU of 2: "a" is evicted locally, still in Redis
    assert len(api) == 2 and api.get("a") == 1.0 and api.stats["shared_hits"] == 1

    monkeypatch.setattr(cache_module, "_shared", lambda: _FakeRedis(fail=True))
    monkeypatch.setattr(cache_module, "_redis_failed", False)
    local_only = _floats()
    local_only.set("x", 9.0)  # Redis down: the write is kept locally, no exception
    assert local_only.get("x") == 9.0 and local_only.get("y") is None


def test_caching_can_be_turned_off(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_module, "get_settings", lambda: settings)
    settings.cache_enabled = False
    cache = _floats()
    cache.set("a", 1.0)
    assert cache.get("a") is None and len(cache) == 0

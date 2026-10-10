from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.core.rate_limit import InMemoryRateLimiter
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SETTINGS = Settings(jwt_secret="unit-test-secret-unit-test-secret-1234")  # type: ignore[arg-type]


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct-horse-42")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct-horse-42", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("x", "not-a-hash")


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id, SETTINGS)
    assert decode_access_token(token, SETTINGS).user_id == user_id


def test_access_token_wrong_secret_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), SETTINGS)
    other = Settings(jwt_secret="another-secret-another-secret-12345")  # type: ignore[arg-type]
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, other)


def test_expired_token_rejected() -> None:
    expired_settings = SETTINGS.model_copy(update={"access_token_ttl_minutes": -1})
    token, _ = create_access_token(uuid.uuid4(), expired_settings)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SETTINGS)


async def test_in_memory_rate_limiter() -> None:
    limiter = InMemoryRateLimiter()
    results = [(await limiter.hit("k", limit=2))[0] for _ in range(3)]
    assert results == [True, True, False]
    assert (await limiter.hit("other", limit=2))[0]


def test_histogram_buckets_are_cumulative() -> None:
    registry = MetricsRegistry()
    registry.observe("latency", 7, route="a")
    registry.observe("latency", 70, route="a")
    text = registry.render_prometheus()
    assert 'latency_bucket{route="a",le="5"} 0' in text
    assert 'latency_bucket{route="a",le="10"} 1' in text
    assert 'latency_bucket{route="a",le="100"} 2' in text
    assert 'latency_bucket{route="a",le="+Inf"} 2' in text

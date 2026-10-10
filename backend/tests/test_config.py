from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import JobBackend, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_is_loadable() -> None:
    """The shipped .env.example must always produce valid settings."""
    settings = Settings(_env_file=REPO_ROOT / ".env.example")  # type: ignore[call-arg]
    assert settings.job_backend == JobBackend.INLINE
    assert settings.cors_origins == ["http://localhost:5173"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test", ["http://a.test"]),
        ("http://a.test, http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test"]', ["http://a.test"]),
    ],
)
def test_cors_origins_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected  # type: ignore[call-arg]

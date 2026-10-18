"""Webhook host validation: Slack/Discord only, never any other host."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.services import webhooks


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.slack.com/services/T000/B000/xxxxxxxxxxxxxxxxxxxx",
        "https://discord.com/api/webhooks/123456789012345678/abcDEF-ghiJKL",
        "https://discordapp.com/api/webhooks/123456789012345678/abcDEF-ghiJKL",
    ],
)
def test_known_webhook_hosts_are_accepted(url: str) -> None:
    webhooks.validate_url(url)  # does not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.slack.com/services/T000/B000/xxxxxxxxxxxxxxxxxxxx",  # not https
        "https://evil.example/services/T000/B000/xxxxxxxxxxxxxxxxxxxx",
        "https://hooks.slack.com.evil.example/x",
        "https://169.254.169.254/latest/meta-data",
        "not a url",
        "",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        webhooks.validate_url(url)


def test_url_hint_shows_only_the_tail() -> None:
    hint = webhooks.url_hint("https://hooks.slack.com/services/T000/B000/xxxxxxxxxxxxxxxxxxxx")
    assert hint == "…xxxxxx"
    assert "T000" not in hint


def test_url_hint_handles_a_short_string() -> None:
    assert webhooks.url_hint("short") == "…"

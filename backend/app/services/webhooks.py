"""Slack/Discord delivery: outbound POSTs to a small, fixed set of webhook hosts — never to
anything else the user types. This is not a general outbound-fetch feature; a saved URL must
resolve to one of these hosts before it is ever stored or sent to, which is what makes it safe
from SSRF (see `safe_fetch.py` for the same posture on arXiv/Crossref GETs).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.models.webhook import NotificationChannel

log = get_logger(__name__)

ALLOWED_HOSTS = {"hooks.slack.com", "discord.com", "discordapp.com"}
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Tests replace this to serve canned responses without the network (same pattern as
# services/arxiv.py's client_factory — monkeypatching httpx.AsyncClient itself would also
# intercept the test client's own calls into the app).
ClientFactory = Callable[[], httpx.AsyncClient]


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)


client_factory: ClientFactory = _make_client


def validate_url(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host not in ALLOWED_HOSTS:
        raise ValidationError(
            "That doesn't look like a Slack or Discord webhook URL.",
            hint="Use an incoming webhook URL from hooks.slack.com or discord.com.",
        )


def url_hint(url: str) -> str:
    return f"…{url[-6:]}" if len(url) >= 10 else "…"


def _body(platform: str, text: str) -> dict[str, str]:
    return {"text": text} if platform == "slack" else {"content": text}


async def send(platform: str, url: str, text: str) -> bool:
    """POST a short message. Never raises — returns whether it looked like it worked."""
    try:
        async with client_factory() as client:
            response = await client.post(url, json=_body(platform, text))
        if response.status_code >= 300:
            log.warning("webhook_send_failed", platform=platform, status=response.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        log.warning("webhook_send_failed", platform=platform, error=repr(exc))
        return False


async def notify_user(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, text: str
) -> None:
    """Best-effort fan-out to every channel this user has configured. Never raises."""
    async with session_factory() as session:
        channels = list(
            (
                await session.execute(
                    select(NotificationChannel).where(NotificationChannel.user_id == user_id)
                )
            ).scalars()
        )
    for channel in channels:
        await send(channel.platform, channel.url, text)

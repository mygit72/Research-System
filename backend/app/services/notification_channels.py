"""CRUD for a user's Slack/Discord webhooks (Settings → Notifications). Sending and host
validation live in `services/webhooks.py`."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.webhook import NotificationChannel
from app.services import webhooks


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[NotificationChannel]:
    rows = await session.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user_id)
        .order_by(NotificationChannel.platform)
    )
    return list(rows.scalars())


async def save(
    session: AsyncSession, user_id: uuid.UUID, platform: str, url: str
) -> NotificationChannel:
    webhooks.validate_url(url)
    existing = await session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id, NotificationChannel.platform == platform
        )
    )
    if existing is not None:
        existing.url = url
        return existing
    channel = NotificationChannel(user_id=user_id, platform=platform, url=url)
    session.add(channel)
    await session.flush()
    return channel


async def delete(session: AsyncSession, user_id: uuid.UUID, platform: str) -> None:
    existing = await session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id, NotificationChannel.platform == platform
        )
    )
    if existing is None:
        raise NotFoundError("No webhook saved for that platform.")
    await session.delete(existing)


async def test(session: AsyncSession, user_id: uuid.UUID, platform: str) -> bool:
    existing = await session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id, NotificationChannel.platform == platform
        )
    )
    if existing is None:
        raise NotFoundError("No webhook saved for that platform.")
    return await webhooks.send(
        platform, existing.url, "Research Intelligence: this is a test notification."
    )

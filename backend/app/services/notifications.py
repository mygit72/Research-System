"""In-app notifications. The only producer today is a Research Watch digest
(`services/agent/runner.py`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.base import utcnow
from app.models.notification import Notification


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str,
    link: str | None = None,
) -> Notification:
    notification = Notification(user_id=user_id, kind=kind, title=title, body=body, link=link)
    session.add(notification)
    await session.flush()
    return notification


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 20, offset: int = 0
) -> tuple[list[Notification], int]:
    query = select(Notification).where(Notification.user_id == user_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotFoundError("Notification not found.")
    if notification.read_at is None:
        notification.read_at = utcnow()
    return notification


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> int:
    now: datetime = utcnow()
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]

"""In-app notifications. The bell dropdown in the frontend reads this directly."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.notification import NotificationOut, UnreadCount
from app.services import notifications as notif

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationOut])
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[NotificationOut]:
    items, total = await notif.list_for_user(db, user.id, limit=limit, offset=offset)
    return Page(
        items=[NotificationOut.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(user: CurrentUser, db: DbSession) -> UnreadCount:
    return UnreadCount(unread=await notif.unread_count(db, user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> NotificationOut:
    return NotificationOut.model_validate(await notif.mark_read(db, user.id, notification_id))


@router.post("/read-all")
async def mark_all_read(user: CurrentUser, db: DbSession) -> dict[str, int]:
    return {"marked": await notif.mark_all_read(db, user.id)}

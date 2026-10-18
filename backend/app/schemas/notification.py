from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import APIModel


class NotificationOut(APIModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int

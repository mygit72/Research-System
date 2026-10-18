"""Slack/Discord delivery for Research Watches: one webhook per platform per account, reused by
every watch the user owns. See `services/webhooks.py` for the fixed-host validation and sending.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookPlatform(StrEnum):
    SLACK = "slack"
    DISCORD = "discord"


class NotificationChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("user_id", "platform"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(Text)
    # The full webhook URL. Not Fernet-encrypted like a model API key (it's a destination to
    # post to, not a credential that reaches elsewhere) but never echoed back in full — see
    # services/webhooks.url_hint, mirroring UserModelChoice.key_hint.
    url: Mapped[str] = mapped_column(Text)

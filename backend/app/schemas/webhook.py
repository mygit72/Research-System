from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel

WebhookPlatformName = Literal["slack", "discord"]


class WebhookSave(BaseModel):
    url: str = Field(min_length=1, max_length=500)


class WebhookOut(APIModel):
    platform: str
    url_hint: str
    updated_at: datetime


class WebhookTestResult(BaseModel):
    ok: bool

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class APIModel(BaseModel):
    """Base for response schemas built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def _utc_datetimes(cls, value: Any) -> Any:
        # SQLite drops tzinfo; all stored times are UTC, so say so explicitly —
        # otherwise browsers parse them as local time.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None
    request_id: str | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int

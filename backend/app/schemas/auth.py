from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import APIModel

MIN_PASSWORD_LENGTH = 10


def _check_password_strength(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.isdigit() or password.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols")
    return password


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    full_name: str = Field(default="", max_length=200)

    _password_strength = field_validator("password")(_check_password_strength)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)

    _password_strength = field_validator("new_password")(_check_password_strength)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class UserPreferences(BaseModel):
    """Known preference keys. Unknown keys are rejected to keep the blob clean."""

    model_config = {"extra": "forbid"}

    theme: Literal["light", "dark", "system"] | None = None
    font_scale: Literal["sm", "md", "lg"] | None = None
    sidebar_collapsed: bool | None = None
    onboarding_completed: bool | None = None
    default_search_mode: Literal["hybrid", "semantic", "keyword"] | None = None
    show_advanced: bool | None = None  # reveal technical panels (passages, retrieval traces)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    preferences: UserPreferences | None = None


class UserResponse(APIModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    preferences: dict[str, Any]
    created_at: datetime
    last_login_at: datetime | None


class SessionResponse(APIModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str
    ip_address: str

"""Which language model a user's AI work runs on, when it isn't the server's default.

The API key (for a hosted provider) is stored encrypted (Fernet, see
services/llm/user_models.py) and never leaves the server again: responses show only its last
characters. Deleting the account deletes the row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserModelChoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_model_choices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # A preset from services/llm/user_models.PRESETS: openai, gemini, groq, openrouter,
    # mistral, custom (any OpenAI-compatible URL) or ollama (a local model).
    preset: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500), default="")  # custom and ollama only
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_hint: Mapped[str] = mapped_column(String(16), default="")  # "…a1b2", for recognition

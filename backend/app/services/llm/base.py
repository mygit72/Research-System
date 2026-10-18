"""LLM provider interface shared by every backend (Ollama, OpenAI-compatible, fake)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class GenerationParams:
    max_tokens: int = 700
    temperature: float = 0.1
    context_window: int | None = None


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class StreamEvent:
    """Either a text delta, or the final event carrying usage and the stop reason."""

    text: str = ""
    done: bool = False
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    model: str | None = None


class LLMError(Exception):
    """Generation failed. `user_message` is safe to show.

    `status` is the provider's HTTP status when there was one, and `retry_after` the seconds
    it asked callers to wait: a busy shared model is retried with them (free_tier.py).
    `sent=False` means no request was made at all, so there is nothing to meter."""

    def __init__(
        self,
        user_message: str,
        detail: str | None = None,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        sent: bool = True,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail
        self.status = status
        self.retry_after = retry_after
        self.sent = sent

    @property
    def busy(self) -> bool:
        """Rate-limited or overloaded: worth trying again after a pause."""
        return self.status == 429 or (self.status is not None and self.status >= 500)


class LLMProvider(Protocol):
    name: str
    model_id: str
    is_remote: bool

    def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]: ...


def count_tokens(text: str) -> int:
    """Rough, provider-independent estimate (~4 chars per token in English) for budgeting."""
    return max(1, (len(text) + 3) // 4)

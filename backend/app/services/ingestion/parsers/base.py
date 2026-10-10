from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.services.ingestion.types import DocumentFormat, RawDocument

ProgressCallback = Callable[[str, float, str | None], None]
"""(stage, fraction 0..1 within the parse step, human message)"""


class ParseError(Exception):
    """A document that cannot be parsed. `user_message` is safe to show."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class ParserProvider(Protocol):
    name: str
    formats: frozenset[DocumentFormat]

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument: ...


def noop_progress(_stage: str, _fraction: float, _message: str | None) -> None:
    return None

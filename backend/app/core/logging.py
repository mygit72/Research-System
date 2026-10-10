"""Structured logging.

Every log line carries contextual fields bound via `structlog.contextvars`
(request_id, user_id, ...). Output is JSON in production and human-readable
in development.
"""

from __future__ import annotations

import logging
import sys

import structlog

# Keys whose values must never reach the logs.
_REDACTED_KEYS = frozenset(
    {"password", "token", "access_token", "refresh_token", "api_key", "secret"}
)


def _redact_secrets(
    _logger: object, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key in event_dict.keys() & _REDACTED_KEYS:
        event_dict[key] = "***"
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_secrets,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    # Route stdlib logging (uvicorn, sqlalchemy) through the same level.
    logging.basicConfig(level=level.upper(), stream=sys.stderr, format="%(name)s: %(message)s")
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # we log requests ourselves


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]

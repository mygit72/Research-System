"""Request-scoped middleware: request IDs, access logging, security headers."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.metrics import metrics

log = get_logger("http")

REQUEST_ID_HEADER = "x-request-id"
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]
# API responses are data, never pages: nothing may load or run from them. Not sent for the
# interactive docs (Swagger UI loads its scripts) or signed files (a PDF opened in a tab must
# keep the browser's viewer working).
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_NO_CSP_PREFIXES = ("/docs", "/redoc", "/api/v1/assets/")


class RequestContextMiddleware:
    """Pure ASGI middleware (streaming-safe, unlike BaseHTTPMiddleware)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(REQUEST_ID_HEADER.encode(), b"").decode()[:64]
        request_id = incoming if incoming.isascii() and incoming else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                    *_SECURITY_HEADERS,
                    *([] if scope["path"].startswith(_NO_CSP_PREFIXES) else [_API_CSP]),
                ]
            await send(message)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            route = scope.get("route")
            path_template = getattr(route, "path", scope["path"])
            user_id = scope.get("state", {}).get("user_id")
            metrics.observe_request(scope["method"], path_template, status_code, duration_ms)
            if path_template not in ("/health", "/ready"):
                log.info(
                    "request",
                    method=scope["method"],
                    path=path_template,
                    status=status_code,
                    duration_ms=duration_ms,
                    user_id=user_id,
                )
            structlog.contextvars.clear_contextvars()

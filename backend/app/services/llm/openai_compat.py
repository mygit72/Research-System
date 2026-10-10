"""OpenAI-compatible chat completions (OpenAI, vLLM, LM Studio, llama.cpp server, ...) via SSE."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.base import GenerationParams, LLMError, Message, StreamEvent, Usage

BUSY = "The language model service is busy. Please try again shortly."


def _retry_after(headers: httpx.Headers) -> float | None:
    """Seconds the service asked us to wait (the Retry-After header, when it is a number)."""
    try:
        return max(0.0, float(headers.get("retry-after", "")))
    except ValueError:
        return None


class OpenAICompatibleProvider:
    name = "openai"
    is_remote = True

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model_id = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        # Provider-specific fields merged into each request (LLM_EXTRA_BODY), e.g. OpenRouter's
        # {"reasoning": {...}}. They can't replace the model, the messages or streaming.
        self.extra_body = extra_body or {}

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        body = {
            **self.extra_body,
            "model": self.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": params.max_tokens,
            "temperature": params.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        usage, stop = Usage(), None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            transport=self.transport,
        ) as client:
            try:
                async with client.stream("POST", "/chat/completions", json=body) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        busy = response.status_code == 429 or response.status_code >= 500
                        raise LLMError(
                            BUSY if busy else "The language model service rejected the request.",
                            detail=f"HTTP {response.status_code}: {response.text[:300]}",
                            status=response.status_code,
                            retry_after=_retry_after(response.headers),
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk.get("error"):
                            # Routers (OpenRouter) answer 200 and report an upstream failure
                            # inside the stream.
                            raise _stream_error(chunk["error"])
                        if chunk.get("usage"):
                            usage = Usage(
                                chunk["usage"].get("prompt_tokens", 0),
                                chunk["usage"].get("completion_tokens", 0),
                            )
                        for choice in chunk.get("choices", []):
                            text = (choice.get("delta") or {}).get("content") or ""
                            if text:
                                yield StreamEvent(text=text)
                            stop = choice.get("finish_reason") or stop
            except httpx.ConnectError as exc:
                raise LLMError(
                    "The language model service is unreachable.", detail=repr(exc)
                ) from exc
            except httpx.TimeoutException as exc:
                raise LLMError(
                    "The language model took too long to respond.", detail=repr(exc)
                ) from exc
        yield StreamEvent(done=True, usage=usage, stop_reason=stop, model=self.model_id)


def _stream_error(error: Any) -> LLMError:
    code = error.get("code") if isinstance(error, dict) else None
    status = code if isinstance(code, int) else None
    message = str(error.get("message", "") if isinstance(error, dict) else error)[:300]
    busy = status is None or status == 429 or status >= 500
    return LLMError(
        BUSY if busy else "The language model service rejected the request.",
        detail=f"In the stream: {code or 'error'}: {message}",
        status=status if status is not None else 502,
    )

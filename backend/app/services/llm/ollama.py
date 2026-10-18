"""Ollama (local models): POST /api/chat with NDJSON streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.services.llm.base import GenerationParams, LLMError, Message, StreamEvent, Usage


class OllamaProvider:
    name = "ollama"
    is_remote = False

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_id = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamEvent]:
        options = {"temperature": params.temperature, "num_predict": params.max_tokens}
        if params.context_window is not None:
            options["num_ctx"] = params.context_window
        body = {
            "model": self.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": options,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            transport=self.transport,
        ) as client:
            try:
                async with client.stream("POST", "/api/chat", json=body) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        if response.status_code == 404:
                            raise LLMError(
                                f"The model “{self.model_id}” isn't installed in Ollama.",
                                detail=f"Run: ollama pull {self.model_id}",
                            )
                        raise LLMError(
                            "The local language model returned an error.",
                            detail=f"HTTP {response.status_code}: {response.text[:300]}",
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise LLMError(
                                "The local language model failed.", detail=str(chunk["error"])
                            )
                        text = chunk.get("message", {}).get("content", "")
                        if chunk.get("done"):
                            yield StreamEvent(
                                text=text,
                                done=True,
                                usage=Usage(
                                    chunk.get("prompt_eval_count", 0), chunk.get("eval_count", 0)
                                ),
                                stop_reason=chunk.get("done_reason"),
                                model=self.model_id,
                            )
                            return
                        if text:
                            yield StreamEvent(text=text)
            except httpx.ConnectError as exc:
                raise LLMError(
                    "Can't reach Ollama. Is it running?",
                    detail=f"Start Ollama at {self.base_url} (install it from https://ollama.com), "
                    f"then run: ollama pull {self.model_id}",
                ) from exc
            except httpx.TimeoutException as exc:
                raise LLMError(
                    "The language model took too long to respond.", detail=repr(exc)
                ) from exc

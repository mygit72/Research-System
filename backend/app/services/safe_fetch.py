"""Outbound requests to a small, fixed set of hosts — never to anything the user typed.

Used by the arXiv and DOI importers. The caller builds every URL from a validated identifier
and names the hosts it may reach; here we additionally require https, follow at most a few
redirects (each re-checked against the same hosts), and stop reading at a size cap.
"""

from __future__ import annotations

import httpx

from app.core.errors import AppError, ValidationError

MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)


async def get_bytes(
    client: httpx.AsyncClient,
    url: str,
    limit: int,
    allowed_hosts: set[str],
    *,
    not_found: str = "Nothing was found for this identifier.",
    service: str = "The service",
) -> bytes:
    for _ in range(MAX_REDIRECTS + 1):
        if not url.startswith("https://") or httpx.URL(url).host not in allowed_hosts:
            raise AppError(f"{service} redirected somewhere unexpected, so the import was stopped.")
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers.get("location", "")))
                continue
            if response.status_code == 404:
                raise ValidationError(not_found)
            if response.status_code >= 400:
                raise AppError(
                    f"{service} didn't answer.",
                    hint="Try again in a minute, or download the PDF and upload it.",
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise ValidationError(
                        "The answer is larger than the allowed size.",
                        hint="Download a smaller version and upload it.",
                    )
            return bytes(body)
    raise AppError(f"{service} redirected too many times.")

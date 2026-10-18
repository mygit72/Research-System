"""Client for the isolated project-code runner service."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import RateLimitedError, ServiceUnavailableError


async def run_toy_experiment(files: dict[str, str], settings: Settings) -> dict[str, Any]:
    """Run a bounded toy experiment through the separately deployed sandbox service."""
    if not settings.project_runner_url or not settings.project_runner_token:
        raise ServiceUnavailableError(
            "The isolated code runner is not configured. Start the Docker Compose stack and set "
            "PROJECT_RUNNER_TOKEN; see the README for setup."
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(55.0, connect=3.0)) as client:
            response = await client.post(
                f"{settings.project_runner_url.rstrip('/')}/v1/run-toy",
                headers={
                    "Authorization": f"Bearer {settings.project_runner_token.get_secret_value()}"
                },
                json={"files": files},
            )
    except httpx.TimeoutException as exc:
        raise ServiceUnavailableError(
            "The isolated runner timed out before returning a result. Try the run again or inspect "
            "the runner service logs."
        ) from exc
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError(
            "The isolated runner could not be reached. Check that the project-runner service is "
            "healthy."
        ) from exc

    if response.status_code == 429:
        raise RateLimitedError("The isolated runner is busy. Try again in a moment.")
    if response.status_code >= 500:
        raise ServiceUnavailableError(
            "The isolated runner could not start this run. Check the runner image and Docker "
            "daemon, then try again."
        )
    if response.status_code >= 400:
        raise ServiceUnavailableError("The isolated runner rejected this project run.")
    try:
        result = response.json()
    except ValueError as exc:
        raise ServiceUnavailableError("The isolated runner returned an invalid response.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("exit_code"), int):
        raise ServiceUnavailableError("The isolated runner returned an incomplete run record.")
    return result

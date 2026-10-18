"""Language models: the server's default (LLM_PROVIDER / LLM_MODEL), or the one the current
user chose in Settings → AI (their own API key, or a local model — see user_models.py).

On a public site the server's model can be a shared free one (FREE_TIER, see free_tier.py).
It sends text to a third party, so it is used only for people who chose it: until a user has
picked the free model, their own key or their own copy of the app, no model is in effect."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.services.llm.base import (
    GenerationParams,
    LLMError,
    LLMProvider,
    Message,
    StreamEvent,
    Usage,
    count_tokens,
)
from app.services.llm.fake import INSUFFICIENT, FakeLLM
from app.services.llm.free_tier import FreeTierLLM, allowance, describe
from app.services.llm.user_models import KeyUnreadable, UserModel, active_model, api_key_of, refusal

if TYPE_CHECKING:
    from app.services.usage import UsageScope

# Sensible model per provider when LLM_MODEL is left empty.
DEFAULT_MODELS = {
    "ollama": "qwen2.5:3b",  # fits next to the embedder + reranker on a CPU-only 8 GB machine
    "fake": FakeLLM.model_id,
}
NOT_CHOSEN = "Choose how to run the AI features first."
NOT_CHOSEN_HINT = (
    "In Settings → AI: this site's free shared model, your own API key, or your own copy of "
    "the app with a local model."
)


def _own_model() -> UserModel | None:
    """The user's own model (their key, or a local model). None when the server's model is
    the one in effect — including for someone who chose the site's shared free model."""
    user = active_model()
    return None if user is None or user.free else user


def _free_tier_user(settings: Settings) -> UserModel | None:
    """On a FREE_TIER server: the user who chose the free shared model, if that's who is
    asking. Nobody else's text may go to it."""
    user = active_model()
    return user if settings.free_tier and user is not None and user.free else None


def on_free_tier(settings: Settings) -> bool:
    """The site's shared free model is what this user's AI work would run on."""
    return settings.free_tier and _own_model() is None


def resolve_model(settings: Settings) -> str:
    user = _own_model()
    if user is not None:
        return user.model
    model = settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")
    if not model:
        raise ServiceUnavailableError(f"Set LLM_MODEL for the “{settings.llm_provider}” provider.")
    return model


def current_model(settings: Settings) -> str:
    """The model in effect (the user's choice, or the server's), "" when none is configured."""
    user = _own_model()
    if user is not None:
        return user.model
    return settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")


def provider_name(settings: Settings) -> str:
    """Who serves the model: the server's provider, or the user's preset (groq, gemini, …).
    Part of cache keys, so results from different models are never mixed."""
    user = _own_model()
    return user.preset if user is not None else settings.llm_provider


def get_llm(settings: Settings, usage: UsageScope | None = None) -> LLMProvider:
    """The configured model, metered: every call is recorded in `llm_usage` (Phase 14).

    `usage` names who the calls are for; without it, the surrounding `usage_scope` is used.
    """
    from app.services.usage import MeteredLLM

    return MeteredLLM(_provider(settings), settings, usage)


def _local_code_model(settings: Settings) -> tuple[str, str] | None:
    """Return the dedicated code model only when this request already uses local Ollama.

    A local coding model must never silently replace a user's hosted provider or the shared
    free-tier choice. In those cases, coding requests stay on the model they selected.
    """
    model = settings.code_llm_model.strip()
    if not model:
        return None
    user = active_model()
    if user is not None:
        if (
            user.free
            or user.provider != "ollama"
            or not _same_ollama_endpoint(user.base_url, settings.ollama_base_url)
        ):
            return None
        return model, user.base_url
    if settings.free_tier or settings.llm_provider != "ollama":
        return None
    return model, settings.ollama_base_url


def _same_ollama_endpoint(left: str, right: str) -> bool:
    """Treat localhost and 127.0.0.1 as the same local Ollama service."""
    try:
        def endpoint(value: str) -> tuple[str, str, int | None, str]:
            parsed = urlsplit(value.rstrip("/"))
            host = (parsed.hostname or "").casefold()
            if host == "localhost":
                host = "127.0.0.1"
            return parsed.scheme.casefold(), host, parsed.port, parsed.path.rstrip("/")

        return endpoint(left) == endpoint(right)
    except ValueError:
        return left.rstrip("/").casefold() == right.rstrip("/").casefold()


def resolve_code_model(settings: Settings) -> str:
    """Model id used for an implementation request, for cache keys and trace records."""
    target = _local_code_model(settings)
    return target[0] if target else resolve_model(settings)


def get_coding_llm(settings: Settings, usage: UsageScope | None = None) -> LLMProvider:
    """Use a configured local code model for local requests; preserve all other choices."""
    target = _local_code_model(settings)
    if target is None:
        return get_llm(settings, usage)

    from app.services.llm.ollama import OllamaProvider
    from app.services.usage import MeteredLLM

    model, base_url = target
    provider = OllamaProvider(model, base_url, timeout=settings.llm_timeout)
    return MeteredLLM(provider, settings, usage)


def _provider(settings: Settings) -> LLMProvider:
    user = _own_model()
    if user is not None:
        return _user_provider(settings, user)
    if not settings.free_tier:
        return server_provider(settings)
    chooser = _free_tier_user(settings)
    if chooser is None:
        raise ServiceUnavailableError(NOT_CHOSEN, hint=NOT_CHOSEN_HINT)
    return FreeTierLLM(server_provider(settings), settings, chooser.user_id)


def server_provider(settings: Settings) -> LLMProvider:
    """The server's own model, unmetered and unpaced (`get_llm` is what features use)."""
    provider = settings.llm_provider
    if provider == "openai" and settings.local_only:  # said before anything about its model
        raise ServiceUnavailableError(
            "Remote language models are disabled (LOCAL_ONLY=true).",
            hint="Use Ollama or turn off local-only mode.",
        )
    model = resolve_model(settings)
    if provider == "fake":
        return FakeLLM()
    if provider == "ollama":
        from app.services.llm.ollama import OllamaProvider

        return OllamaProvider(model, settings.ollama_base_url, timeout=settings.llm_timeout)
    if provider == "openai":
        from app.services.llm.openai_compat import OpenAICompatibleProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        if not key:
            raise ServiceUnavailableError("OPENAI_API_KEY is not configured.")
        return OpenAICompatibleProvider(
            model,
            key,
            settings.llm_api_base,
            settings.llm_timeout,
            extra_body=settings.llm_extra_body,
        )
    raise ServiceUnavailableError(f"Unknown language model provider “{provider}”.")


def _user_provider(settings: Settings, user: UserModel) -> LLMProvider:
    """The user's own choice. Built only from what they saved: the server's own keys are never
    sent to an address a user chose."""
    problem = refusal(settings, user)
    if problem:
        raise ServiceUnavailableError(problem)
    try:
        key = api_key_of(settings, user)
    except KeyUnreadable as exc:
        raise ServiceUnavailableError(
            "Your saved API key can't be read anymore (the server's secret changed).",
            hint="Enter it again in Settings → AI.",
        ) from exc
    provider: LLMProvider
    if user.provider == "ollama":
        from app.services.llm.ollama import OllamaProvider

        provider = OllamaProvider(user.model, user.base_url, timeout=settings.llm_timeout)
    else:
        from app.services.llm.openai_compat import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(user.model, key, user.base_url, settings.llm_timeout)
        provider.is_remote = user.remote
    provider.name = user.preset  # shown on the usage page: groq, gemini, ollama, …
    return provider


async def llm_status(settings: Settings) -> dict[str, Any]:
    """Configured model plus a quick availability check (no generation, no secrets)."""
    user = _own_model()
    if user is not None:
        return await _user_status(settings, user)
    provider = settings.llm_provider
    model = settings.llm_model or DEFAULT_MODELS.get(provider, "")
    remote = provider == "openai"
    status: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "remote": remote,
        "source": "server",
    }
    if settings.free_tier:
        chooser = _free_tier_user(settings)
        about = describe(settings, model)
        status |= {"source": "free", "label": about["label"], "host": about["host"]}
        if chooser is None:
            status |= {"source": "none", "ready": False}
            return status | {"problem": NOT_CHOSEN, "hint": NOT_CHOSEN_HINT}
        left = await allowance(settings, chooser.user_id)
        if left.problem:
            return status | {"ready": False, "problem": left.problem, "hint": left.hint}
    if remote and settings.local_only:
        return status | {"ready": False, "problem": "Remote models are disabled (LOCAL_ONLY)."}
    if provider == "ollama":
        return status | await _ollama_status(settings.ollama_base_url, model)
    key = settings.openai_api_key
    if remote and not (key and key.get_secret_value()):
        return status | {"ready": False, "problem": "OPENAI_API_KEY is not configured."}
    return status | {"ready": True}


async def _ollama_status(base_url: str, model: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
        installed = [m.get("name", "") for m in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return {
            "ready": False,
            "problem": f"Ollama isn't reachable at {base_url}.",
            "hint": "Install it from https://ollama.com and start it, then run: "
            f"ollama pull {model}",
        }
    if not {model, f"{model}:latest"} & set(installed):
        return {
            "ready": False,
            "problem": f"The model “{model}” isn't installed in Ollama.",
            "hint": f"Run: ollama pull {model}",
            "installed": installed,
        }
    return {"ready": True}


async def _user_status(settings: Settings, user: UserModel) -> dict[str, Any]:
    status: dict[str, Any] = {
        "provider": user.preset,
        "model": user.model,
        "remote": user.remote,
        "source": "user",
        "label": user.label,
        "key_hint": user.key_hint,
    }
    problem = refusal(settings, user)
    if problem:
        return status | {"ready": False, "problem": problem}
    try:
        api_key_of(settings, user)
    except KeyUnreadable:
        return status | {
            "ready": False,
            "problem": "Your saved API key can't be read anymore.",
            "hint": "Enter it again in Settings → AI.",
        }
    if user.provider == "ollama":
        return status | await _ollama_status(user.base_url, user.model)
    return status | {"ready": True}  # a hosted key is checked by "Test connection", not here


__all__ = [
    "INSUFFICIENT",
    "FakeLLM",
    "GenerationParams",
    "LLMError",
    "LLMProvider",
    "Message",
    "StreamEvent",
    "Usage",
    "count_tokens",
    "current_model",
    "describe",
    "get_coding_llm",
    "get_llm",
    "llm_status",
    "on_free_tier",
    "provider_name",
    "resolve_code_model",
    "resolve_model",
    "server_provider",
]

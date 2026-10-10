"""Each user's own language model: the server's default, their own API key, or a local model.

Settings → AI lets a user choose:

* the **server's default** model (nothing stored) — or, on a public site whose model is a
  shared free one (`FREE_TIER`), that model once they have chosen it (preset `free`: no key,
  no address; see free_tier.py);
* a **hosted provider with their own API key** — OpenAI, Google Gemini, Groq, OpenRouter,
  Mistral (several have free tiers). Their AI work then runs on, and is billed
  to, their key;
* a **local model** — Ollama on the machine running this server, or any OpenAI-compatible URL
  (LM Studio, vLLM, a llama.cpp server). Only where the server allows it (`local_models_allowed`):
  on a self-hosted install, not on a public server, which must not reach into its own network.

How a choice takes effect: once per request (`get_current_user`) and once per background job
(`workers/runner.py`), the user's choice is loaded into a context variable. `get_llm`,
`resolve_model`, `provider_name` and `llm_status` read it, so every AI feature — chat,
summaries, comparisons, reviews, the project builder — and every cache key and readiness check
follow the user's choice without each feature knowing about it.

Keys: encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) under `MODEL_KEY_SECRET`, or a
key derived from `JWT_SECRET` when that isn't set. A key is decrypted only to build the provider
for a call, never logged, never returned (responses show its last four characters), and never
sent anywhere but its provider's fixed address. The server's own provider keys are never sent
to an address a user chose. Note what "private" means here: other users and anyone holding a
copy of the database can't read a key, but the server has to decrypt it to make calls.
"""

from __future__ import annotations

import base64
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ValidationError
from app.models.model_choice import UserModelChoice

# The saved choice "this site's shared free model". Not in PRESETS: the user gives no key, no
# address and no model; the server's own are used (and its key goes only to its own address).
FREE = "free"


@dataclass(frozen=True, slots=True)
class Preset:
    label: str
    provider: str  # how it's called: openai (any compatible API) | ollama
    base_url: str  # fixed for hosted presets; the default for ollama; empty for custom
    keys_url: str  # where to create a key
    note: str
    local: bool = False  # reaches a private address: only where local models are allowed
    needs_key: bool = True


FREE_NOTE = (
    "Has a free tier with rate limits. Check its current terms: free tiers may use what you "
    "send to improve their models."
)
PRESETS: dict[str, Preset] = {
    "openai": Preset(
        "OpenAI",
        "openai",
        "https://api.openai.com/v1",
        "https://platform.openai.com/api-keys",
        "Paid per token.",
    ),
    "gemini": Preset(
        "Google Gemini",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "https://aistudio.google.com/apikey",
        FREE_NOTE,
    ),
    "groq": Preset(
        "Groq",
        "openai",
        "https://api.groq.com/openai/v1",
        "https://console.groq.com/keys",
        FREE_NOTE,
    ),
    "openrouter": Preset(
        "OpenRouter",
        "openai",
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/keys",
        "One key for many providers; models ending in “:free” cost nothing (rate-limited).",
    ),
    "mistral": Preset(
        "Mistral",
        "openai",
        "https://api.mistral.ai/v1",
        "https://console.mistral.ai/api-keys",
        FREE_NOTE,
    ),
    "custom": Preset(
        "Other OpenAI-compatible server",
        "openai",
        "",
        "",
        "LM Studio, vLLM, a llama.cpp server, or any API that speaks OpenAI's chat format. "
        "The key is optional.",
        local=True,
        needs_key=False,
    ),
    "ollama": Preset(
        "Ollama (a model on your computer)",
        "ollama",
        "http://localhost:11434",
        "",
        "Install Ollama from https://ollama.com, then `ollama pull <model>`. Any model you pull "
        "can be used.",
        local=True,
        needs_key=False,
    ),
}


# --- encryption -------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _fernet(secret: str) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"research-intelligence/user-model-keys",
        info=b"fernet",
    ).derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _secret(settings: Settings) -> str:
    return (settings.model_key_secret or settings.jwt_secret).get_secret_value()


def encrypt_key(settings: Settings, api_key: str) -> str:
    return _fernet(_secret(settings)).encrypt(api_key.encode()).decode()


class KeyUnreadable(Exception):
    """The saved key was encrypted under a secret the server no longer has."""


def decrypt_key(settings: Settings, token: str) -> str:
    try:
        return _fernet(_secret(settings)).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise KeyUnreadable from exc


def key_hint(api_key: str) -> str:
    return f"…{api_key[-4:]}" if len(api_key) >= 12 else "…"


# --- the active user's model --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserModel:
    user_id: uuid.UUID
    preset: str
    provider: str
    model: str
    base_url: str
    encrypted_key: str | None
    key_hint: str

    @property
    def free(self) -> bool:
        """They chose the site's shared free model: the server's model, not one of their own."""
        return self.preset == FREE

    @property
    def remote(self) -> bool:
        return self.free or not PRESETS[self.preset].local

    @property
    def label(self) -> str:
        return "Free shared model" if self.free else PRESETS[self.preset].label


_active: ContextVar[UserModel | None] = ContextVar("user_model", default=None)


def active_model() -> UserModel | None:
    return _active.get()


def activate(model: UserModel | None) -> Any:
    """Make `model` the one AI calls in this context use (None: the server's default).
    Returns a token for `deactivate`."""
    return _active.set(model)


def deactivate(token: Any) -> None:
    _active.reset(token)


def to_user_model(choice: UserModelChoice) -> UserModel | None:
    if choice.preset == FREE:
        return UserModel(choice.user_id, FREE, "", "", "", None, "")
    preset = PRESETS.get(choice.preset)
    if preset is None:  # a preset removed in an upgrade: back to the server's default
        return None
    return UserModel(
        user_id=choice.user_id,
        preset=choice.preset,
        provider=preset.provider,
        model=choice.model,
        base_url=choice.base_url or preset.base_url,
        encrypted_key=choice.api_key_encrypted,
        key_hint=choice.key_hint,
    )


async def load_choice(session: AsyncSession, user_id: uuid.UUID) -> UserModelChoice | None:
    return (
        await session.execute(select(UserModelChoice).where(UserModelChoice.user_id == user_id))
    ).scalar_one_or_none()


async def load_user_model(session: AsyncSession, user_id: uuid.UUID | None) -> UserModel | None:
    if user_id is None:
        return None
    choice = await load_choice(session, user_id)
    return to_user_model(choice) if choice is not None else None


def api_key_of(settings: Settings, model: UserModel) -> str:
    """The plaintext key, for building a provider. Raises KeyUnreadable."""
    return decrypt_key(settings, model.encrypted_key) if model.encrypted_key else ""


def refusal(settings: Settings, model: UserModel) -> str | None:
    """Why this server can't use the user's choice right now, or None."""
    if model.remote and settings.local_only:
        return (
            "This server only allows local models (LOCAL_ONLY), so your API key can't be used. "
            "Choose a local model or the server's default in Settings → AI."
        )
    if model.remote and not settings.allow_user_api_keys:
        return (
            "This server doesn't accept personal API keys. Choose another option in Settings → AI."
        )
    if not model.remote and not settings.local_models_allowed:
        return (
            "This server can't reach local models. Run the app on your own computer to use one, "
            "or choose an API key in Settings → AI."
        )
    return None


# --- validating a choice ------------------------------------------------------------------------

_MODEL = re.compile(r"^[\w.:/@+\-]{1,200}$")
_KEY = re.compile(r"^\S{8,400}$")


def check_url(url: str) -> str:
    url = url.strip().rstrip("/")
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as exc:
        raise ValidationError("That address isn't a valid URL.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValidationError("The address must start with http:// or https://.")
    if parsed.userinfo:
        raise ValidationError("Put the key in the key field, not in the address.")
    if len(url) > 500:
        raise ValidationError("That address is too long.")
    return url


@dataclass(frozen=True, slots=True)
class CheckedChoice:
    preset: str
    model: str
    base_url: str
    api_key: str | None  # None: keep the saved key (same preset), "" : no key


def check_choice(
    settings: Settings,
    preset_name: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    saved: UserModelChoice | None,
) -> CheckedChoice:
    if preset_name == FREE:
        if not settings.free_tier:
            raise ValidationError("This server has no free shared model.")
        return CheckedChoice(FREE, "", "", "")  # "": a key saved for another provider is dropped
    preset = PRESETS.get(preset_name)
    if preset is None:
        raise ValidationError(f"Unknown provider “{preset_name}”.")
    problem = refusal(
        settings, UserModel(uuid.uuid4(), preset_name, preset.provider, "", "", None, "")
    )
    if problem:
        raise ValidationError(problem)
    model = (model or "").strip()
    if not _MODEL.match(model):
        raise ValidationError(
            "Choose a model: press “Test connection” to list the ones your key can use.",
        )
    url = ""
    if preset.local:
        url = check_url(base_url or preset.base_url)
    if api_key is not None:
        api_key = api_key.strip()
        if api_key and not _KEY.match(api_key):
            raise ValidationError("That doesn't look like an API key (no spaces, 8+ characters).")
    keep = saved is not None and saved.preset == preset_name and saved.api_key_encrypted
    if preset.needs_key and not api_key and not keep:
        raise ValidationError(f"Enter your {preset.label} API key.")
    return CheckedChoice(preset_name, model, url, api_key or (None if keep else ""))


# --- testing a connection: list the models the key (or the local server) offers ------------------


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    ok: bool
    models: list[str]
    message: str


async def list_models(
    settings: Settings,
    preset_name: str,
    base_url: str,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConnectionResult:
    """Ask the provider which models this key (or this local server) can use. Costs nothing:
    no text is generated. Never follows redirects."""
    preset = PRESETS[preset_name]
    url = base_url or preset.base_url
    if preset.provider == "ollama":
        path, headers = "/api/tags", {}
    else:
        path, headers = "/models", ({"Authorization": f"Bearer {api_key}"} if api_key else {})
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, transport=transport
        ) as client:
            response = await client.get(url + path, headers=headers)
    except httpx.ConnectError:
        hint = " Is Ollama running?" if preset.provider == "ollama" else ""
        return ConnectionResult(False, [], f"Can't reach {url}.{hint}")
    except httpx.HTTPError as exc:
        return ConnectionResult(False, [], f"{preset.label} didn't answer ({type(exc).__name__}).")
    if response.status_code in (401, 403):
        return ConnectionResult(False, [], f"{preset.label} rejected the key.")
    if response.status_code >= 400:
        return ConnectionResult(
            False, [], f"{preset.label} answered HTTP {response.status_code}: {response.text[:200]}"
        )
    try:
        data = response.json()
        items = data["models"] if preset.provider == "ollama" else data["data"]
        names = [m["name"] if preset.provider == "ollama" else m["id"] for m in items]
    except (ValueError, KeyError, TypeError):
        return ConnectionResult(False, [], f"{url} answered, but not like {preset.label}.")
    names = sorted({str(n) for n in names})[:500]
    if not names and preset.provider == "ollama":
        return ConnectionResult(
            True, [], "Ollama is running but has no models yet: ollama pull <model>"
        )
    return ConnectionResult(True, names, f"Connected: {len(names)} model(s) available.")


def describe_options(settings: Settings) -> dict[str, Any]:
    """What the settings page may offer on this server."""
    return {
        "presets": [
            {
                "id": key,
                "label": p.label,
                "provider": p.provider,
                "base_url": p.base_url,
                "keys_url": p.keys_url,
                "note": p.note,
                "local": p.local,
                "needs_key": p.needs_key,
                "available": refusal(
                    settings, UserModel(uuid.uuid4(), key, p.provider, "", "", None, "")
                )
                is None,
            }
            for key, p in PRESETS.items()
        ],
        "allow_user_api_keys": settings.allow_user_api_keys and not settings.local_only,
        "allow_local_models": settings.local_models_allowed,
    }

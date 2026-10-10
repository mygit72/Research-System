"""Settings → AI: which language model the signed-in user's AI work runs on.

The server's default, a hosted provider with the user's own API key, or a local model (where
the server allows it). The key is write-only: it's encrypted on arrival and responses show only
its last characters. See services/llm/user_models.py.

On a site whose model is a shared free one (FREE_TIER), that model is a choice too (preset
`free`), made here: nothing is sent to it for a user who hasn't picked it.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, SettingsDep, rate_limit
from app.core.config import Settings
from app.core.errors import ValidationError
from app.models.model_choice import UserModelChoice
from app.services.audit import record_audit
from app.services.llm import DEFAULT_MODELS, describe, llm_status
from app.services.llm.free_tier import allowance
from app.services.llm.user_models import (
    FREE,
    PRESETS,
    KeyUnreadable,
    activate,
    check_choice,
    check_url,
    decrypt_key,
    describe_options,
    encrypt_key,
    key_hint,
    list_models,
    load_choice,
    refusal,
    to_user_model,
)

router = APIRouter(prefix="/users/me/model", tags=["account"])
TEST_LIMIT = [Depends(rate_limit("model-test", "auth_rate_limit_per_minute"))]


class ModelChoiceRequest(BaseModel):
    preset: str = Field(max_length=32)  # a provider, or "free": this site's shared free model
    model: str = Field(default="", max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    # Omit to keep the key already saved for this provider.
    api_key: str | None = Field(default=None, max_length=400)


class ConnectionTestRequest(BaseModel):
    preset: str = Field(max_length=32)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=400)  # omit: use the saved key


async def _view(
    settings: Settings, user_id: uuid.UUID, choice: UserModelChoice | None
) -> dict[str, Any]:
    server_model = settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")
    saved = None
    free = None
    if settings.free_tier:
        chosen = choice is not None and choice.preset == FREE
        free = describe(settings, server_model) | {"chosen": chosen}
        free |= (await allowance(settings, user_id)).as_dict()
        if choice is not None and chosen:
            saved = {
                "preset": FREE,
                "label": free["label"],
                "model": server_model,
                "base_url": "",
                "has_key": False,
                "key_hint": "",
                "updated_at": choice.updated_at,
            }
    if choice is not None and choice.preset in PRESETS:
        preset = PRESETS[choice.preset]
        saved = {
            "preset": choice.preset,
            "label": preset.label,
            "model": choice.model,
            "base_url": choice.base_url or preset.base_url,
            "has_key": bool(choice.api_key_encrypted),
            "key_hint": choice.key_hint,
            "updated_at": choice.updated_at,
        }
    return {
        "choice": saved,
        "server_default": {"provider": settings.llm_provider, "model": server_model},
        # The shared free model, when this site has one: who hosts it, today's allowance.
        "free_tier": free,
        "download_url": settings.download_url,
        "options": describe_options(settings),
        "status": await llm_status(settings),  # for the model now in effect
    }


@router.get("", summary="The model your AI work runs on, and the choices this server offers")
async def get_model(user: CurrentUser, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    return await _view(settings, user.id, await load_choice(db, user.id))


@router.put("", summary="Use your own API key, a local model, or the site's free model")
async def set_model(
    body: ModelChoiceRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    saved = await load_choice(db, user.id)
    checked = check_choice(settings, body.preset, body.model, body.base_url, body.api_key, saved)
    choice = saved or UserModelChoice(user_id=user.id)
    if saved is None:
        db.add(choice)
    choice.preset, choice.model, choice.base_url = checked.preset, checked.model, checked.base_url
    new_key = checked.api_key
    if new_key is not None:  # a new key, or "" for none; None keeps the saved one
        choice.api_key_encrypted = encrypt_key(settings, new_key) if new_key else None
        choice.key_hint = key_hint(new_key) if new_key else ""
    await record_audit(
        db,
        "user.model_changed",
        user_id=user.id,
        ip_address=request.client.host if request.client else "",
        details={"preset": checked.preset, "model": checked.model},  # never the key
    )
    await db.flush()
    await db.refresh(choice)
    activate(to_user_model(choice))  # the rest of this request already uses it
    return await _view(settings, user.id, choice)


@router.delete("", summary="Undo your choice (forgets your key): the server's default again")
async def reset_model(
    request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    saved = await load_choice(db, user.id)
    if saved is not None:
        await db.delete(saved)
        await record_audit(
            db,
            "user.model_reset",
            user_id=user.id,
            ip_address=request.client.host if request.client else "",
        )
        await db.flush()
    activate(None)
    return await _view(settings, user.id, None)


@router.post(
    "/test",
    summary="Check a key or a local server: lists the models it offers (generates nothing)",
    dependencies=TEST_LIMIT,
)
async def test_model(
    body: ConnectionTestRequest, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    preset = PRESETS.get(body.preset)
    if preset is None:
        raise ValidationError(f"Unknown provider “{body.preset}”.")
    candidate = to_user_model(UserModelChoice(user_id=user.id, preset=body.preset, model=""))
    if candidate is None:  # unreachable: the preset exists
        raise ValidationError(f"Unknown provider “{body.preset}”.")
    problem = refusal(settings, candidate)
    if problem:
        raise ValidationError(problem)
    # Hosted presets go only to their fixed address; a URL is taken only for local models.
    url = check_url(body.base_url or preset.base_url) if preset.local else preset.base_url
    key = (body.api_key or "").strip()
    if not key:
        saved = await load_choice(db, user.id)
        if saved is not None and saved.preset == body.preset and saved.api_key_encrypted:
            try:
                key = decrypt_key(settings, saved.api_key_encrypted)
            except KeyUnreadable as exc:
                raise ValidationError(
                    "Your saved key can't be read anymore: enter it again."
                ) from exc
    if preset.needs_key and not key:
        raise ValidationError(f"Enter your {preset.label} API key.")
    result = await list_models(settings, body.preset, url, key)
    return {"ok": result.ok, "models": result.models, "message": result.message}

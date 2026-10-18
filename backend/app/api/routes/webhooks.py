"""Settings → Notifications: one Slack and/or Discord webhook per account, reused by every
watch. See `services/webhooks.py` for the fixed-host validation and sending."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.models.webhook import NotificationChannel
from app.schemas.webhook import WebhookOut, WebhookSave, WebhookTestResult
from app.services import notification_channels as channels
from app.services.webhooks import url_hint

router = APIRouter(prefix="/users/me/webhooks", tags=["account"])
TEST_LIMIT = [Depends(rate_limit("webhook-test", "auth_rate_limit_per_minute"))]


def _out(channel: NotificationChannel) -> WebhookOut:
    return WebhookOut(
        platform=channel.platform, url_hint=url_hint(channel.url), updated_at=channel.updated_at
    )


@router.get("", summary="Your saved Slack/Discord webhooks (URLs are never shown in full)")
async def list_webhooks(user: CurrentUser, db: DbSession) -> list[WebhookOut]:
    return [_out(c) for c in await channels.list_for_user(db, user.id)]


@router.put("/{platform}", summary="Save (or replace) the webhook for this platform")
async def save_webhook(
    platform: str, body: WebhookSave, user: CurrentUser, db: DbSession
) -> WebhookOut:
    channel = await channels.save(db, user.id, platform, body.url.strip())
    await db.flush()
    await db.refresh(channel)
    return _out(channel)


@router.delete("/{platform}", summary="Remove the webhook for this platform")
async def delete_webhook(platform: str, user: CurrentUser, db: DbSession) -> None:
    await channels.delete(db, user.id, platform)


@router.post(
    "/{platform}/test",
    summary="Send a test message (generates nothing, just posts)",
    dependencies=TEST_LIMIT,
)
async def test_webhook(platform: str, user: CurrentUser, db: DbSession) -> WebhookTestResult:
    return WebhookTestResult(ok=await channels.test(db, user.id, platform))

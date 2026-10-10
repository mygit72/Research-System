from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record_audit(
    session: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Append an audit entry in the caller's transaction (committed with the change)."""
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            ip_address=ip_address,
            details=details or {},
        )
    )

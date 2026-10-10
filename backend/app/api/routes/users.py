from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep, SettingsDep
from app.core.errors import NotFoundError
from app.models.audit import AuditLog
from app.models.document import Document
from app.repositories.users import RefreshTokenRepository, UserRepository
from app.schemas.auth import SessionResponse, UserResponse, UserUpdateRequest
from app.services.audit import record_audit
from app.services.export_data import build_export, export_filename
from app.services.storage import get_storage

router = APIRouter(prefix="/users/me", tags=["account"])


@router.get("", response_model=UserResponse)
async def get_me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("", response_model=UserResponse)
async def update_me(body: UserUpdateRequest, user: CurrentUser, db: DbSession) -> UserResponse:
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.preferences is not None:
        # Merge (don't replace) so clients can update one preference at a time.
        updates = body.preferences.model_dump(exclude_none=True)
        user.preferences = {**(user.preferences or {}), **updates}
    await db.flush()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(user: CurrentUser, db: DbSession) -> list[SessionResponse]:
    tokens = await RefreshTokenRepository(db).list_active(user.id, datetime.now(UTC))
    return [SessionResponse.model_validate(t) for t in tokens]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    tokens = await RefreshTokenRepository(db).list_active(user.id, datetime.now(UTC))
    match = next((t for t in tokens if t.id == session_id), None)
    if match is None:
        raise NotFoundError("Session not found.")
    match.revoked_at = datetime.now(UTC)
    await record_audit(db, "user.session_revoked", user_id=user.id, resource_id=str(session_id))


@router.get("/activity", summary="Your security activity: sign-ins, sessions, deletions, exports")
async def activity(
    user: CurrentUser, db: DbSession, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "ip_address": r.ip_address,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get(
    "/export",
    summary="Download everything you own as a .zip (data as JSON, plus your original files)",
    response_class=StreamingResponse,
)
async def export(
    request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> StreamingResponse:
    archive = await build_export(db, get_storage(settings), user)
    await record_audit(
        db,
        "user.exported",
        user_id=user.id,
        ip_address=request.client.host if request.client else "",
    )
    await db.commit()

    def chunks() -> Any:
        with archive:
            while block := archive.read(1024 * 1024):
                yield block

    filename = export_filename(user.id)
    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, db: DbSession, documents: DocumentServiceDep) -> None:
    """Permanently delete the account and everything it owns.

    Rows cascade from the user; papers go through the normal deletion first so their files,
    rendered pages and search-index vectors are removed too (after the commit).
    """
    for document_id in (
        await db.execute(select(Document.id).where(Document.user_id == user.id))
    ).scalars():
        await documents.delete(user.id, document_id)
    await record_audit(db, "user.deleted", user_id=None, resource_id=str(user.id))
    await UserRepository(db).delete(user)

"""Signed binary assets: thumbnails, rendered pages and original files.

Authorized by the signature (see core/signing.py), not the bearer token, so they
work in <img> tags and can be cached by the browser.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.deps import DbSession, SettingsDep
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.signing import verify_scope
from app.models.document import DocumentVersion
from app.services.ingestion.render import cached_page_png
from app.services.storage import get_storage

router = APIRouter(prefix="/assets", tags=["assets"])

CACHE_HEADERS = {"Cache-Control": "private, max-age=3600"}
Expires = Annotated[int, Query(alias="exp")]
Signature = Annotated[str, Query(alias="sig", max_length=64)]


async def _authorized_version(
    version_id: uuid.UUID, exp: int, sig: str, db: DbSession, settings: SettingsDep
) -> DocumentVersion:
    if not verify_scope(f"version:{version_id}", exp, sig, settings):
        raise PermissionDeniedError(
            "This link has expired.", hint="Reload the page to get a fresh link."
        )
    version = await db.get(DocumentVersion, version_id)
    if version is None:
        raise NotFoundError("File not found.")
    return version


@router.get("/versions/{version_id}/thumbnail.png")
async def thumbnail(
    version_id: uuid.UUID, exp: Expires, sig: Signature, db: DbSession, settings: SettingsDep
) -> FileResponse:
    await _authorized_version(version_id, exp, sig, db, settings)
    path = get_storage(settings).derived_dir(version_id) / "thumb.png"
    if not path.exists():
        raise NotFoundError("No preview available.")
    return FileResponse(path, media_type="image/png", headers=CACHE_HEADERS)


@router.get("/versions/{version_id}/pages/{page}.png")
async def page_image(
    version_id: uuid.UUID,
    page: int,
    exp: Expires,
    sig: Signature,
    db: DbSession,
    settings: SettingsDep,
    w: int = Query(default=800, ge=100, le=2400),
) -> FileResponse:
    version = await _authorized_version(version_id, exp, sig, db, settings)
    if not version.paginated or not version.page_count or not 1 <= page <= version.page_count:
        raise NotFoundError("That page doesn't exist.")
    storage = get_storage(settings)
    path = await asyncio.to_thread(
        cached_page_png, storage.path(version.storage_key), storage.derived_dir(version_id), page, w
    )
    return FileResponse(path, media_type="image/png", headers=CACHE_HEADERS)


@router.get("/versions/{version_id}/file")
async def original_file(
    version_id: uuid.UUID, exp: Expires, sig: Signature, db: DbSession, settings: SettingsDep
) -> FileResponse:
    version = await _authorized_version(version_id, exp, sig, db, settings)
    path = get_storage(settings).path(version.storage_key)
    if not path.exists():
        raise NotFoundError("The original file is missing.")
    # Only PDFs render inline; HTML etc. always download (never execute user HTML on our origin).
    disposition = "inline" if version.mime_type == "application/pdf" else "attachment"
    return FileResponse(
        path,
        media_type=version.mime_type,
        filename=version.original_filename,
        content_disposition_type=disposition,
        headers={**CACHE_HEADERS, "Content-Security-Policy": "sandbox"},
    )

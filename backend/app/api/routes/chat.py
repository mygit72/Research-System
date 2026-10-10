from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.core.database import get_session_factory
from app.core.errors import NotFoundError, RateLimitedError, ValidationError
from app.models.chat import ChatMessage, Conversation, ConversationScope
from app.models.document import Document
from app.schemas.chat import (
    AskIn,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from app.schemas.common import ErrorResponse, Page
from app.services.organization import collection_document_ids, get_collection
from app.services.rag import answer_question

router = APIRouter(prefix="/chat", tags=["chat"])

# Answers being written per user (this process). Each one keeps the language model busy for
# tens of seconds on a CPU, so one user can't start more than CHAT_MAX_CONCURRENT_PER_USER.
_answering: dict[uuid.UUID, int] = {}


async def _owned(db: DbSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("Conversation not found.")
    return conversation


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    db: DbSession,
    document_id: uuid.UUID | None = Query(default=None, description="Chats about this paper"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ConversationOut]:
    base = select(Conversation).where(Conversation.user_id == user.id)
    rows = list((await db.execute(base.order_by(Conversation.updated_at.desc()))).scalars())
    if document_id is not None:  # JSON list membership, portable across SQLite/PostgreSQL
        rows = [c for c in rows if str(document_id) in (c.document_ids or [])]
    return Page(
        items=[ConversationOut.model_validate(c) for c in rows[offset : offset + limit]],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: CurrentUser, db: DbSession
) -> ConversationOut:
    ids = list(dict.fromkeys(body.document_ids))
    collection = None
    if body.collection_id is not None:
        collection = await get_collection(db, user.id, body.collection_id)
        ids = list(dict.fromkeys([*ids, *await collection_document_ids(db, collection.id)]))
        if not ids:
            raise ValidationError("This collection has no papers yet.")
    if ids:
        owned = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.id.in_(ids), Document.user_id == user.id)
        )
        if owned != len(ids):
            raise ValidationError("Some of the selected papers don't exist.")
    conversation = Conversation(
        user_id=user.id,
        title=body.title or "New conversation",
        scope=ConversationScope.PAPERS if ids else ConversationScope.LIBRARY,
        document_ids=[str(i) for i in ids],
        collection_id=collection.id if collection else None,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConversationDetail:
    conversation = await _owned(db, user.id, conversation_id)
    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id)
            .options(selectinload(ChatMessage.citations))
            .order_by(ChatMessage.created_at)
        )
    ).scalars()
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, db: DbSession
) -> ConversationOut:
    conversation = await _owned(db, user.id, conversation_id)
    conversation.title = body.title.strip()
    await db.flush()
    await db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    await db.delete(await _owned(db, user.id, conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    summary="Ask a question; the answer streams back as server-sent events",
    responses={200: {"content": {"text/event-stream": {}}}, 404: {"model": ErrorResponse}},
)
async def ask(
    conversation_id: uuid.UUID,
    body: AskIn,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> StreamingResponse:
    await _owned(db, user.id, conversation_id)  # 404 before the stream starts
    question = " ".join(body.content.split())
    if not question:
        raise ValidationError("Ask a question.")
    if _answering.get(user.id, 0) >= settings.chat_max_concurrent_per_user:
        raise RateLimitedError(
            "You already have answers being written.",
            hint="Wait for them to finish, or stop one, then ask again.",
        )
    user_id = user.id

    async def events() -> AsyncIterator[str]:
        _answering[user_id] = _answering.get(user_id, 0) + 1
        stream = answer_question(
            get_session_factory(), settings, user_id, conversation_id, question, body.fresh
        )
        try:
            async for event in stream:
                yield _sse(event)
        finally:
            await stream.aclose()  # persists a partial answer if the client went away
            _answering[user_id] -= 1
            if not _answering[user_id]:
                del _answering[user_id]

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

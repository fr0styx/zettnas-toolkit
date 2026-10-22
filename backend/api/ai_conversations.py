"""
ai_conversations.py — REST API router for ZettAI conversation history management.

Provides multi-user conversation management:
- GET /api/ai/conversations: list threads with search & pinning
- POST /api/ai/conversations: create thread
- GET /api/ai/conversations/{conv_id}: retrieve thread messages
- PATCH /api/ai/conversations/{conv_id}: rename, pin, archive
- DELETE /api/ai/conversations/{conv_id}: delete thread
- DELETE /api/ai/conversations: clear all threads
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services.ai_conversations_db import (
    append_message,
    clear_all_conversations,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_with_messages,
    list_conversations,
    update_conversation,
)

router = APIRouter(tags=["AI Conversation History"])


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default="New Conversation", max_length=120)
    model: str | None = Field(default="", max_length=256)
    id: str | None = Field(default=None, max_length=64)
    meta: dict[str, Any] | None = None


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    is_pinned: bool | None = None
    is_archived: bool | None = None
    model: str | None = Field(default=None, max_length=256)
    title_customized: bool | None = None


class ConversationMessageAppendRequest(BaseModel):
    role: str = Field(..., max_length=32)
    content: str = Field(..., min_length=1, max_length=20000)
    telemetry: dict[str, Any] | None = None
    tools_called: list[dict[str, Any]] | None = None
    web_sources: list[dict[str, Any]] | None = None
    citations: list[dict[str, Any]] | None = None
    photos: list[dict[str, Any]] | None = None


def _get_principal_uid(principal: AuthenticatedPrincipal) -> str:
    """Extracts unique user identifier for conversation tenancy isolation."""
    return (principal.user_id or principal.username or "admin").strip().lower()


@router.get(
    "/ai/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/media/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_list_conversations(
    search: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=60, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Lists conversations for the authenticated user."""
    uid = _get_principal_uid(principal)
    convs = list_conversations(
        user_id=uid,
        search=search,
        include_archived=include_archived,
        limit=limit,
    )
    return {"status": "ok", "conversations": convs, "count": len(convs)}


@router.post(
    "/ai/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/media/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_create_conversation(
    req: ConversationCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Creates a new conversation thread."""
    uid = _get_principal_uid(principal)
    conv = create_conversation(
        user_id=uid,
        title=req.title or "New Conversation",
        model=req.model or "",
        conv_id=req.id,
        meta=req.meta,
    )
    return {"status": "ok", "conversation": conv}


@router.get(
    "/ai/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/media/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_get_conversation(
    conv_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Retrieves full conversation with ordered message stream."""
    uid = _get_principal_uid(principal)
    conv = get_conversation_with_messages(conv_id, uid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied.")
    return {"status": "ok", "conversation": conv}


@router.patch(
    "/ai/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.patch(
    "/media/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_update_conversation(
    conv_id: str,
    req: ConversationUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Updates editable metadata on a conversation thread (title, pin, archive)."""
    uid = _get_principal_uid(principal)
    conv = update_conversation(
        conv_id=conv_id,
        user_id=uid,
        title=req.title,
        is_pinned=req.is_pinned,
        is_archived=req.is_archived,
        model=req.model,
        title_customized=req.title_customized,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied.")
    return {"status": "ok", "conversation": conv}


@router.delete(
    "/ai/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.delete(
    "/media/conversations/{conv_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_delete_conversation(
    conv_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Deletes a conversation thread and its message stream permanently."""
    uid = _get_principal_uid(principal)
    ok = delete_conversation(conv_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied.")
    return {"status": "ok", "deleted": True, "id": conv_id}


@router.delete(
    "/ai/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.delete(
    "/media/conversations",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_clear_all_conversations(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Deletes all conversations belonging to the authenticated user."""
    uid = _get_principal_uid(principal)
    cnt = clear_all_conversations(uid)
    return {"status": "ok", "deleted_count": cnt}


@router.post(
    "/ai/conversations/{conv_id}/messages",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def api_append_conversation_message(
    conv_id: str,
    req: ConversationMessageAppendRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Appends an explicit message turn to a conversation thread."""
    uid = _get_principal_uid(principal)
    # Verify conversation ownership
    conv = get_conversation(conv_id, uid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied.")

    msg = append_message(
        conv_id=conv_id,
        user_id=uid,
        role=req.role,
        content=req.content,
        telemetry=req.telemetry,
        tools_called=req.tools_called,
        web_sources=req.web_sources,
        citations=req.citations,
        photos=req.photos,
    )
    return {"status": "ok", "message": msg}

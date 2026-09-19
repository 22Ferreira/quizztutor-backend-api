from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.rbac import get_current_user, get_optional_user, ensure_attempt_owner
from app.models import User
from app.models.attempt import Attempt
from app.models.chat import ChatThread, ChatMessage
from app.schemas.chat import ThreadOut, MessageOut, SendMessageRequest
from app.services.audit import event

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/threads", response_model=ThreadOut)
async def create_or_get_thread(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_owner(attempt, me)

    # Check if thread already exists
    existing_q = await db.execute(select(ChatThread).where(ChatThread.attempt_id == attempt.id))
    existing = existing_q.scalar_one_or_none()
    if existing:
        return ThreadOut(id=existing.id, attempt_id=existing.attempt_id)

    thread = ChatThread(attempt_id=attempt.id)
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return ThreadOut(id=thread.id, attempt_id=thread.attempt_id)


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_messages(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: str | None = Query(default=None, description="Cursor: busca mensagens antes deste ID"),
):
    thread_q = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = thread_q.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread não encontrada")
    att_q = await db.execute(select(Attempt).where(Attempt.id == thread.attempt_id))
    ensure_attempt_owner(att_q.scalar_one_or_none(), me)

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )

    # Cursor-based: busca mensagens anteriores ao ID informado
    if before_id:
        ref_q = await db.execute(
            select(ChatMessage.created_at).where(ChatMessage.id == before_id)
        )
        ref_ts = ref_q.scalar_one_or_none()
        if ref_ts:
            stmt = stmt.where(ChatMessage.created_at < ref_ts)

    msgs_q = await db.execute(stmt)
    msgs = list(reversed(msgs_q.scalars().all()))  # ordem cronológica crescente
    return [
        MessageOut(
            id=m.id,
            thread_id=m.thread_id,
            role=m.role,
            content=m.content if not m.deleted_at else "[Mensagem removida]",
            out_of_scope=m.out_of_scope,
            created_at=m.created_at,
            deleted_at=m.deleted_at,
        )
        for m in msgs
    ]


@router.post("/threads/{thread_id}/messages", response_model=MessageOut)
async def send_message(
    thread_id: str,
    payload: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    thread_q = await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
    thread = thread_q.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread não encontrada")
    att_q = await db.execute(select(Attempt).where(Attempt.id == thread.attempt_id))
    ensure_attempt_owner(att_q.scalar_one_or_none(), me)

    msg = ChatMessage(
        thread_id=thread.id,
        user_id=me.id if me else None,
        role="USER",
        content=payload.content,
        out_of_scope=False,
    )
    db.add(msg)
    await event(db, str(me.id) if me else None, "CHAT_MESSAGE_SENT", {"thread_id": thread_id})
    await db.commit()
    await db.refresh(msg)
    return MessageOut(
        id=msg.id,
        thread_id=msg.thread_id,
        role=msg.role,
        content=msg.content,
        out_of_scope=msg.out_of_scope,
        created_at=msg.created_at,
        deleted_at=msg.deleted_at,
    )

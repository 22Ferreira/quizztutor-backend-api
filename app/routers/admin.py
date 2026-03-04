from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import User, UserRole
from app.models.quiz import Quiz, QuizStatus
from app.models.classroom import Class
from app.models.attempt import Attempt
from app.models.audit import AuditLog, EventLog
from app.models.chat import ChatMessage
from app.schemas.users import UserOut
from app.services.audit import audit
from pydantic import BaseModel
from uuid import UUID

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles("ADMIN"))])


class SetRoleRequest(BaseModel):
    role: UserRole


class BanRequest(BaseModel):
    hours: int = 24
    reason: str | None = None


class ModerateMessageRequest(BaseModel):
    reason: str


@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(User))
    users = q.scalars().all()
    return [UserOut(
        id=u.id, email=u.email, name=u.name, role=u.role,
        active=u.active, must_change_password=u.must_change_password,
        banned_until=u.banned_until,
    ) for u in users]


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    payload: SetRoleRequest,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    before_role = user.role.value
    user.role = payload.role
    await audit(db, me.id, "SET_USER_ROLE", "User", user.id, before={"role": before_role}, after={"role": payload.role.value})
    await db.commit()
    return {"message": "ok", "new_role": payload.role.value}


@router.patch("/users/{user_id}/active")
async def toggle_user_active(
    user_id: str,
    active: bool,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    before = user.active
    user.active = active
    if active:
        # bump token_version to revoke existing sessions when deactivating
        user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "SET_USER_ACTIVE", "User", user.id, before={"active": before}, after={"active": active})
    await db.commit()
    return {"message": "ok", "active": active}


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str,
    payload: BanRequest,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.banned_until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
    user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "BAN_USER", "User", user.id, after={"hours": payload.hours, "reason": payload.reason})
    await db.commit()
    return {"message": "banned", "banned_until": user.banned_until.isoformat()}


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.banned_until = None
    await audit(db, me.id, "UNBAN_USER", "User", user.id, after={})
    await db.commit()
    return {"message": "unbanned"}


@router.post("/users/{user_id}/revoke-sessions")
async def admin_revoke_sessions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "ADMIN_REVOKE_SESSIONS", "User", user.id, after={})
    await db.commit()
    return {"message": "sessions revoked"}


@router.get("/quizzes")
async def list_all_quizzes(db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Quiz))
    quizzes = q.scalars().all()
    return [{"id": str(qz.id), "title": qz.title, "status": qz.status.value, "mode": qz.mode.value} for qz in quizzes]


@router.post("/quizzes/{quiz_id}/close")
async def admin_close_quiz(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    quiz.status = QuizStatus.CLOSED
    await audit(db, me.id, "ADMIN_CLOSE_QUIZ", "Quiz", quiz.id, after={"status": "CLOSED"})
    await db.commit()
    return {"message": "closed"}


@router.get("/classes")
async def list_all_classes(db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Class))
    classes = q.scalars().all()
    return [{"id": str(c.id), "name": c.name, "active": c.active} for c in classes]


@router.post("/classes/{class_id}/deactivate")
async def deactivate_class(
    class_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(Class).where(Class.id == class_id))
    c = q.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")
    c.active = False
    await audit(db, me.id, "ADMIN_DEACTIVATE_CLASS", "Class", c.id, after={"active": False})
    await db.commit()
    return {"message": "deactivated"}


@router.get("/audit")
async def get_audit_log(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    logs = q.scalars().all()
    return [
        {
            "id": str(l.id),
            "actor_user_id": str(l.actor_user_id) if l.actor_user_id else None,
            "action": l.action,
            "entity": l.entity,
            "entity_id": l.entity_id,
            "before": l.before,
            "after": l.after,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


@router.get("/analytics/platform")
async def platform_analytics(db: AsyncSession = Depends(get_db)):
    users_q = await db.execute(select(func.count()).where(User.active == True))
    quizzes_q = await db.execute(select(func.count()).where(Quiz.status == "PUBLISHED"))
    attempts_q = await db.execute(select(func.count()).where(Attempt.status == "SUBMITTED"))
    return {
        "active_users": users_q.scalar(),
        "published_quizzes": quizzes_q.scalar(),
        "submitted_attempts": attempts_q.scalar(),
    }


@router.delete("/chat/messages/{message_id}")
async def moderate_message(
    message_id: str,
    payload: ModerateMessageRequest,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    msg = q.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.deleted_at = datetime.now(timezone.utc)
    msg.deleted_by = me.id
    msg.delete_reason = payload.reason
    await audit(db, me.id, "MODERATE_CHAT_MESSAGE", "ChatMessage", msg.id, after={"reason": payload.reason})
    await db.commit()
    return {"message": "moderated"}

"""
admin.py — Área administrativa completa
Todos os endpoints são protegidos por require_roles("ADMIN").
"""
from __future__ import annotations
import io, csv, secrets, string
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user, invalidate_user_cache
from app.utils.security import hash_password
from app.models import User, UserRole
from app.models.quiz import Quiz, QuizStatus
from app.models.classroom import Class, ClassEnrollment
from app.models.attempt import Attempt, AttemptStatus
from app.models.audit import AuditLog, TutorInteraction
from app.models.chat import ChatMessage
from app.models.live_session import LiveSession, LiveSessionStatus
from app.schemas.users import UserOut
from app.services.audit import audit

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles("ADMIN"))],)

# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

class SetRoleRequest(BaseModel):
    role: UserRole

class BanRequest(BaseModel):
    hours: int = 24
    reason: str | None = None

class ModerateMessageRequest(BaseModel):
    reason: str = "Moderado pelo administrador"

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    role: UserRole = UserRole.ALUNO
    password: str

class PatchUserRequest(BaseModel):
    name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None

class PatchQuizRequest(BaseModel):
    status: str
    note: str | None = None

class PatchClassRequest(BaseModel):
    professor_id: str | None = None
    name: str | None = None
    active: bool | None = None

class PatchConfigRequest(BaseModel):
    max_students_per_class: int | None = None
    max_attempts_per_quiz: int | None = None
    max_questions_per_quiz: int | None = None
    max_classes_per_prof: int | None = None
    session_timeout_minutes: int | None = None
    min_password_length: int | None = None
    require_uppercase: bool | None = None
    tutor_enabled: bool | None = None
    chat_enabled: bool | None = None
    max_tutor_requests_per_day: int | None = None
    allow_self_register: bool | None = None
    require_email_verify: bool | None = None


# Config em memória (sem tabela — pode ser migrado para DB depois)
_SYSTEM_CONFIG: dict[str, Any] = {
    "max_students_per_class": 60,
    "max_attempts_per_quiz": 5,
    "max_questions_per_quiz": 100,
    "max_classes_per_prof": 20,
    "session_timeout_minutes": 480,
    "min_password_length": 8,
    "require_uppercase": True,
    "tutor_enabled": True,
    "chat_enabled": True,
    "max_tutor_requests_per_day": 50,
    "allow_self_register": True,
    "require_email_verify": False,}

# ──────────────────────────────────────────────────────────────────────────────
# STATS — Dashboard KPIs
# ──────────────────────────────────────────────────────────────────────────────

_MONTH_ABBR_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
_WEEKDAY_ABBR_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


async def _series_by_month(db: AsyncSession, date_col, months: int = 6) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = _add_months(now.replace(day=1), -(months - 1))
    period = func.date_trunc("month", date_col)
    rows = (await db.execute(
        select(period.label("period"), func.count().label("cnt"))
        .where(date_col >= start)
        .group_by(period)
    )).all()
    counts = {r.period.replace(tzinfo=None).date(): r.cnt for r in rows}
    out = []
    cursor = start
    for _ in range(months):
        out.append({"label": _MONTH_ABBR_PT[cursor.month - 1], "value": counts.get(cursor.date(), 0)})
        cursor = _add_months(cursor, 1)
    return out


async def _series_by_day(db: AsyncSession, date_col, filters: list = None, days: int = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    period = func.date_trunc("day", date_col)
    stmt = select(period.label("period"), func.count().label("cnt")).where(date_col >= start)
    for f in (filters or []):
        stmt = stmt.where(f)
    rows = (await db.execute(stmt.group_by(period))).all()
    counts = {r.period.replace(tzinfo=None).date(): r.cnt for r in rows}
    out = []
    cursor = start
    for _ in range(days):
        out.append({"label": _WEEKDAY_ABBR_PT[cursor.weekday()], "value": counts.get(cursor.date(), 0)})
        cursor += timedelta(days=1)
    return out


async def _series_by_week(db: AsyncSession, date_col, weeks: int = 6) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(weeks=weeks - 1))
    period = func.date_trunc("week", date_col)
    rows = (await db.execute(
        select(period.label("period"), func.count().label("cnt"))
        .where(date_col >= func.date_trunc("week", start))
        .group_by(period)
    )).all()
    counts = {r.period.replace(tzinfo=None).date(): r.cnt for r in rows}
    week_start = func.date_trunc("week", start)
    cursor_dt = start - timedelta(days=start.weekday())  # Monday of the starting week
    cursor_dt = cursor_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for i in range(weeks):
        out.append({"label": f"S{i + 1}", "value": counts.get(cursor_dt.date(), 0)})
        cursor_dt += timedelta(weeks=1)
    return out


@router.get("/stats")
async def platform_stats(db: AsyncSession = Depends(get_db)):
    total_users    = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_profs    = (await db.execute(select(func.count(User.id)).where(User.role == UserRole.PROFESSOR))).scalar() or 0
    total_students = (await db.execute(select(func.count(User.id)).where(User.role == UserRole.ALUNO))).scalar() or 0
    total_classes  = (await db.execute(select(func.count(Class.id)).where(Class.active == True))).scalar() or 0
    pub_quizzes    = (await db.execute(select(func.count(Quiz.id)).where(Quiz.status == QuizStatus.PUBLISHED))).scalar() or 0
    total_attempts = (await db.execute(select(func.count(Attempt.id)).where(Attempt.status == AttemptStatus.SUBMITTED))).scalar() or 0
    tutor_count    = (await db.execute(select(func.count(TutorInteraction.id)))).scalar() or 0
    live_active    = (await db.execute(
        select(func.count(LiveSession.id)).where(LiveSession.status.in_([LiveSessionStatus.LOBBY, LiveSessionStatus.RUNNING]))
    )).scalar() or 0

    user_growth      = await _series_by_month(db, User.created_at, months=6)
    attempts_by_day  = await _series_by_day(db, Attempt.submitted_at, filters=[Attempt.status == AttemptStatus.SUBMITTED], days=7)
    quizzes_by_week  = await _series_by_week(db, Quiz.created_at, weeks=6)
    tutor_by_day     = await _series_by_day(db, TutorInteraction.created_at, days=7)

    return {
        "total_users": total_users,
        "total_professors": total_profs,
        "total_students": total_students,
        "total_classes": total_classes,
        "published_quizzes": pub_quizzes,
        "total_attempts": total_attempts,
        "tutor_interactions": tutor_count,
        "live_sessions_active": live_active,
        "user_growth": user_growth,
        "attempts_by_day": attempts_by_day,
        "quizzes_by_week": quizzes_by_week,
        "tutor_by_day": tutor_by_day,
    }

# ──────────────────────────────────────────────────────────────────────────────
# USERS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    role: str | None = Query(default=None),
):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    stmt = stmt.order_by(User.name).limit(limit).offset(offset)
    users = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(u.id), "email": u.email, "name": u.name,
            "role": u.role.value, "is_active": u.active,
            "must_change_password": u.must_change_password,
            "banned_until": u.banned_until.isoformat() if u.banned_until else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]

@router.post("/users", status_code=201)
async def create_user(
    payload: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "E-mail já cadastrado.")
    if len(payload.password) < 6:
        raise HTTPException(422, "Senha deve ter ao menos 6 caracteres.")
    new_user = User(email=payload.email, name=payload.name, role=payload.role,
                    password_hash=hash_password(payload.password), active=True)
    db.add(new_user)
    await db.flush()
    await audit(db, me.id, "ADMIN_CREATE_USER", "User", new_user.id,
                after={"email": payload.email, "role": payload.role.value})
    await db.commit()
    return {"id": str(new_user.id), "email": new_user.email, "role": new_user.role.value}

@router.patch("/users/{user_id}")
async def patch_user(
    user_id: str, payload: PatchUserRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado.")
    before = {"name": user.name, "role": user.role.value, "active": user.active}
    after: dict = {}
    if payload.name is not None:
        user.name = payload.name; after["name"] = payload.name
    if payload.role is not None:
        user.role = payload.role; invalidate_user_cache(str(user.id)); after["role"] = payload.role.value
    if payload.is_active is not None:
        user.active = payload.is_active
        if not payload.is_active:
            user.token_version = int(user.token_version) + 1
        after["active"] = payload.is_active
    await audit(db, me.id, "ADMIN_PATCH_USER", "User", user.id, before=before, after=after)
    await db.commit()
    return {"message": "ok", "updated": after}

@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado.")
    alphabet = string.ascii_letters + string.digits
    new_pass = "".join(secrets.choice(alphabet) for _ in range(12))
    user.password_hash = hash_password(new_pass)
    user.must_change_password = True
    user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "ADMIN_RESET_PASSWORD", "User", user.id, after={"must_change_password": True})
    await db.commit()
    return {"message": "Senha resetada.", "temporary_password": new_pass, "must_change": True}

@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str, payload: SetRoleRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    before_role = user.role.value
    user.role = payload.role
    invalidate_user_cache(str(user.id))
    await audit(db, me.id, "SET_USER_ROLE", "User", user.id,
                before={"role": before_role}, after={"role": payload.role.value})
    await db.commit()
    return {"message": "ok", "new_role": payload.role.value}

@router.patch("/users/{user_id}/active")
async def toggle_user_active(
    user_id: str, active: bool,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    before = user.active
    user.active = active
    if not active:
        user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "SET_USER_ACTIVE", "User", user.id,
                before={"active": before}, after={"active": active})
    await db.commit()
    return {"message": "ok", "active": active}

@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str, payload: BanRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.banned_until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
    invalidate_user_cache(str(user.id))
    user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "BAN_USER", "User", user.id,
                after={"hours": payload.hours, "reason": payload.reason})
    await db.commit()
    return {"message": "banned", "banned_until": user.banned_until.isoformat()}

@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.banned_until = None
    await audit(db, me.id, "UNBAN_USER", "User", user.id, after={})
    await db.commit()
    return {"message": "unbanned"}

@router.post("/users/{user_id}/revoke-sessions")
async def revoke_sessions(
    user_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.token_version = int(user.token_version) + 1
    await audit(db, me.id, "ADMIN_REVOKE_SESSIONS", "User", user.id, after={})
    await db.commit()
    return {"message": "sessions revoked"}

# ──────────────────────────────────────────────────────────────────────────────
# PROFESSORS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/professors")
async def list_professors(db: AsyncSession = Depends(get_db)):
    profs = (await db.execute(
        select(User).where(User.role == UserRole.PROFESSOR).order_by(User.name)
    )).scalars().all()

    result = []
    for p in profs:
        class_count   = (await db.execute(select(func.count(Class.id)).where(Class.professor_id == p.id, Class.active == True))).scalar() or 0
        quiz_count    = (await db.execute(select(func.count(Quiz.id)).where(Quiz.professor_id == p.id))).scalar() or 0
        student_count = (await db.execute(
            select(func.count(ClassEnrollment.id))
            .join(Class, ClassEnrollment.class_id == Class.id)
            .where(Class.professor_id == p.id, ClassEnrollment.status == "JOINED")
        )).scalar() or 0
        attempt_count = (await db.execute(
            select(func.count(Attempt.id)).join(Quiz, Attempt.quiz_id == Quiz.id)
            .where(Quiz.professor_id == p.id)
        )).scalar() or 0
        result.append({
            "id": str(p.id), "email": p.email, "name": p.name,
            "role": p.role.value, "is_active": p.active,
            "class_count": class_count, "quiz_count": quiz_count,
            "student_count": student_count, "attempt_count": attempt_count,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return result

@router.get("/professors/{professor_id}/stats")
async def professor_stats(professor_id: str, db: AsyncSession = Depends(get_db)):
    prof = (await db.execute(
        select(User).where(User.id == professor_id, User.role == UserRole.PROFESSOR)
    )).scalar_one_or_none()
    if not prof:
        raise HTTPException(404, "Professor não encontrado.")

    total_classes     = (await db.execute(select(func.count(Class.id)).where(Class.professor_id == prof.id, Class.active == True))).scalar() or 0
    total_quizzes     = (await db.execute(select(func.count(Quiz.id)).where(Quiz.professor_id == prof.id))).scalar() or 0
    published_quizzes = (await db.execute(select(func.count(Quiz.id)).where(Quiz.professor_id == prof.id, Quiz.status == QuizStatus.PUBLISHED))).scalar() or 0
    total_students    = (await db.execute(
        select(func.count(ClassEnrollment.id)).join(Class, ClassEnrollment.class_id == Class.id)
        .where(Class.professor_id == prof.id, ClassEnrollment.status == "JOINED")
    )).scalar() or 0
    total_attempts    = (await db.execute(
        select(func.count(Attempt.id)).join(Quiz, Attempt.quiz_id == Quiz.id).where(Quiz.professor_id == prof.id)
    )).scalar() or 0
    recent_quizzes    = [
        {"title": qz.title, "status": qz.status.value}
        for qz in (await db.execute(
            select(Quiz).where(Quiz.professor_id == prof.id).order_by(Quiz.created_at.desc()).limit(5)
        )).scalars().all()
    ]

    return {
        "total_classes": total_classes, "total_quizzes": total_quizzes,
        "published_quizzes": published_quizzes, "total_students": total_students,
        "total_attempts": total_attempts, "recent_quizzes": recent_quizzes,
    }

# ──────────────────────────────────────────────────────────────────────────────
# QUIZZES
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/quizzes")
async def list_all_quizzes(db: AsyncSession = Depends(get_db)):
    quizzes = (await db.execute(select(Quiz).order_by(Quiz.created_at.desc()))).scalars().all()
    result = []
    for qz in quizzes:
        att_count = (await db.execute(select(func.count(Attempt.id)).where(Attempt.quiz_id == qz.id))).scalar() or 0
        result.append({
            "id": str(qz.id), "title": qz.title, "status": qz.status.value,
            "mode": qz.mode.value, "professor_id": str(qz.professor_id),
            "professor_name": qz.professor.name if qz.professor else None,
            "professor_email": qz.professor.email if qz.professor else None,
            "question_count": len(qz.questions), "attempt_count": att_count,
            "created_at": qz.created_at.isoformat() if qz.created_at else None,
        })
    return result

@router.patch("/quizzes/{quiz_id}")
async def patch_quiz(
    quiz_id: str, payload: PatchQuizRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    quiz = (await db.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if not quiz:
        raise HTTPException(404, "Quiz não encontrado.")
    # "BLOCKED" mapeia para CLOSED (enum existente não tem BLOCKED)
    status_map = {"BLOCKED": "CLOSED", "ARCHIVED": "ARCHIVED", "PUBLISHED": "PUBLISHED", "CLOSED": "CLOSED"}
    new_status_str = status_map.get(payload.status.upper())
    if not new_status_str:
        raise HTTPException(422, f"Status inválido: {payload.status}")
    before = quiz.status.value
    quiz.status = QuizStatus[new_status_str]
    await audit(db, me.id, "ADMIN_PATCH_QUIZ", "Quiz", quiz.id,
                before={"status": before}, after={"status": new_status_str, "note": payload.note})
    await db.commit()
    return {"message": "ok", "status": new_status_str}

@router.post("/quizzes/{quiz_id}/close")
async def admin_close_quiz(
    quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    quiz = (await db.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if not quiz:
        raise HTTPException(404, "Quiz not found")
    quiz.status = QuizStatus.CLOSED
    await audit(db, me.id, "ADMIN_CLOSE_QUIZ", "Quiz", quiz.id, after={"status": "CLOSED"})
    await db.commit()
    return {"message": "closed"}

@router.delete("/quizzes/{quiz_id}", status_code=204)
async def delete_quiz(
    quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    quiz = (await db.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if not quiz:
        raise HTTPException(404, "Quiz não encontrado.")
    title = quiz.title
    await db.delete(quiz)
    await audit(db, me.id, "ADMIN_DELETE_QUIZ", "Quiz", quiz_id, after={"title": title})
    await db.commit()

# ──────────────────────────────────────────────────────────────────────────────
# CLASSES / TURMAS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/classes")
async def list_all_classes(db: AsyncSession = Depends(get_db)):
    classes = (await db.execute(select(Class).order_by(Class.name))).scalars().all()
    result = []
    for c in classes:
        student_count = (await db.execute(
            select(func.count(ClassEnrollment.id))
            .where(ClassEnrollment.class_id == c.id, ClassEnrollment.status == "JOINED")
        )).scalar() or 0
        result.append({
            "id": str(c.id), "name": c.name, "discipline": c.discipline,
            "active": c.active, "invite_code": c.code_entry,
            "professor_id": str(c.professor_id),
            "professor_name": c.professor.name if c.professor else None,
            "professor_email": c.professor.email if c.professor else None,
            "student_count": student_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return result

@router.get("/classes/{class_id}")
async def get_class_detail(class_id: str, db: AsyncSession = Depends(get_db)):
    c = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Turma não encontrada.")
    enrollments = (await db.execute(
        select(ClassEnrollment).where(ClassEnrollment.class_id == c.id, ClassEnrollment.status == "JOINED")
    )).scalars().all()
    students = [
        {"name": e.user.name if e.user else None, "email": e.user.email if e.user else e.invited_email}
        for e in enrollments
    ]
    return {
        "id": str(c.id), "name": c.name, "discipline": c.discipline,
        "invite_code": c.code_entry, "active": c.active,
        "professor_name": c.professor.name if c.professor else None,
        "professor_email": c.professor.email if c.professor else None,
        "student_count": len(students), "students": students,
    }

@router.patch("/classes/{class_id}")
async def patch_class(
    class_id: str, payload: PatchClassRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    c = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Turma não encontrada.")
    before = {"professor_id": str(c.professor_id), "name": c.name, "active": c.active}
    after: dict = {}
    if payload.professor_id is not None:
        new_prof = (await db.execute(
            select(User).where(User.id == payload.professor_id, User.role == UserRole.PROFESSOR)
        )).scalar_one_or_none()
        if not new_prof:
            raise HTTPException(404, "Professor não encontrado.")
        c.professor_id = new_prof.id
        after["professor_id"] = str(new_prof.id)
        after["professor_name"] = new_prof.name
    if payload.name is not None:
        c.name = payload.name; after["name"] = payload.name
    if payload.active is not None:
        c.active = payload.active; after["active"] = payload.active
    await audit(db, me.id, "ADMIN_PATCH_CLASS", "Class", c.id, before=before, after=after)
    await db.commit()
    return {"message": "ok", "updated": after}

@router.post("/classes/{class_id}/deactivate")
async def deactivate_class(
    class_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    c = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Class not found")
    c.active = False
    await audit(db, me.id, "ADMIN_DEACTIVATE_CLASS", "Class", c.id, after={"active": False})
    await db.commit()
    return {"message": "deactivated"}

@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(
    class_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    c = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Turma não encontrada.")
    name = c.name
    await db.delete(c)
    await audit(db, me.id, "ADMIN_DELETE_CLASS", "Class", class_id, after={"name": name})
    await db.commit()

# ──────────────────────────────────────────────────────────────────────────────
# AUDIT — enriquecida com user_email
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    entity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    stmt = stmt.limit(limit).offset(offset)
    logs = (await db.execute(stmt)).scalars().all()

    actor_ids = list({str(l.actor_user_id) for l in logs if l.actor_user_id})
    users_map: dict[str, str] = {}
    if actor_ids:
        uq = (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
        users_map = {str(u.id): u.email for u in uq}

    return [
        {
            "id": str(l.id),
            "actor_user_id": str(l.actor_user_id) if l.actor_user_id else None,
            "user_email": users_map.get(str(l.actor_user_id), "—") if l.actor_user_id else "—",
            "action": l.action, "entity": l.entity, "entity_id": l.entity_id,
            "before": l.before, "after": l.after, "ip": l.ip,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]

# ──────────────────────────────────────────────────────────────────────────────
# CHAT / MESSAGES
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/messages")
async def list_messages(
    type: str = Query(default="CHAT"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    msgs = (await db.execute(
        select(ChatMessage)
        .where(ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [
        {
            "id": str(m.id), "thread_id": str(m.thread_id), "role": m.role,
            "content": m.content, "type": "CHAT",
            "user_id": str(m.user_id) if m.user_id else None,
            "user_name": m.user.name if m.user else None,
            "user_email": m.user.email if m.user else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]

@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    msg = (await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))).scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Mensagem não encontrada.")
    msg.deleted_at = datetime.now(timezone.utc)
    msg.deleted_by = me.id
    msg.delete_reason = "Moderado pelo administrador"
    await audit(db, me.id, "MODERATE_CHAT_MESSAGE", "ChatMessage", msg.id, after={"reason": "admin"})
    await db.commit()

# Legado — endpoint com body de reason
@router.delete("/chat/messages/{message_id}")
async def moderate_message_legacy(
    message_id: str, payload: ModerateMessageRequest,
    db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user),
):
    msg = (await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))).scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.deleted_at = datetime.now(timezone.utc)
    msg.deleted_by = me.id
    msg.delete_reason = payload.reason
    await audit(db, me.id, "MODERATE_CHAT_MESSAGE", "ChatMessage", msg.id, after={"reason": payload.reason})
    await db.commit()
    return {"message": "moderated"}

# ──────────────────────────────────────────────────────────────────────────────
# ANALYTICS (retrocompatibilidade)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/analytics/platform")
async def platform_analytics(db: AsyncSession = Depends(get_db)):
    return {
        "active_users": (await db.execute(select(func.count()).where(User.active == True))).scalar(),
        "published_quizzes": (await db.execute(select(func.count()).where(Quiz.status == QuizStatus.PUBLISHED))).scalar(),
        "submitted_attempts": (await db.execute(select(func.count()).where(Attempt.status == AttemptStatus.SUBMITTED))).scalar(),
    }

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    return _SYSTEM_CONFIG

@router.patch("/config")
async def patch_config(
    payload: PatchConfigRequest,
    me: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    _SYSTEM_CONFIG.update(updated)
    await audit(db, me.id, "ADMIN_PATCH_CONFIG", "SystemConfig", None, after=updated)
    await db.commit()
    return {"message": "ok", "updated": updated, "config": _SYSTEM_CONFIG}

# ──────────────────────────────────────────────────────────────────────────────
# REPORTS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/reports/{report_type}")
async def export_report(
    report_type: str,
    format: str = Query(default="csv"),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows: list[list] = []
    headers: list[str] = []

    if report_type == "users":
        headers = ["ID", "Nome", "Email", "Papel", "Ativo", "Criado em"]
        for u in (await db.execute(select(User).order_by(User.name))).scalars().all():
            rows.append([str(u.id), u.name, u.email, u.role.value,
                         "Sim" if u.active else "Não",
                         u.created_at.strftime("%d/%m/%Y") if u.created_at else ""])

    elif report_type == "quizzes":
        headers = ["ID", "Título", "Professor", "Status", "Questões", "Tentativas", "Criado em"]
        for qz in (await db.execute(select(Quiz).order_by(Quiz.created_at.desc()))).scalars().all():
            att = (await db.execute(select(func.count(Attempt.id)).where(Attempt.quiz_id == qz.id))).scalar() or 0
            rows.append([str(qz.id), qz.title, qz.professor.name if qz.professor else "",
                         qz.status.value, len(qz.questions), att,
                         qz.created_at.strftime("%d/%m/%Y") if qz.created_at else ""])

    elif report_type == "classes":
        headers = ["ID", "Nome", "Professor", "Disciplina", "Alunos", "Ativa", "Criado em"]
        for c in (await db.execute(select(Class).order_by(Class.name))).scalars().all():
            sc = (await db.execute(
                select(func.count(ClassEnrollment.id)).where(ClassEnrollment.class_id == c.id, ClassEnrollment.status == "JOINED")
            )).scalar() or 0
            rows.append([str(c.id), c.name, c.professor.name if c.professor else "",
                         c.discipline or "", sc, "Sim" if c.active else "Não",
                         c.created_at.strftime("%d/%m/%Y") if c.created_at else ""])

    elif report_type == "performance":
        headers = ["Métrica", "Valor"]
        rows = [
            ["Total usuários",       (await db.execute(select(func.count(User.id)))).scalar() or 0],
            ["Professores",          (await db.execute(select(func.count(User.id)).where(User.role == UserRole.PROFESSOR))).scalar() or 0],
            ["Alunos",               (await db.execute(select(func.count(User.id)).where(User.role == UserRole.ALUNO))).scalar() or 0],
            ["Turmas ativas",        (await db.execute(select(func.count(Class.id)).where(Class.active == True))).scalar() or 0],
            ["Quizzes publicados",   (await db.execute(select(func.count(Quiz.id)).where(Quiz.status == QuizStatus.PUBLISHED))).scalar() or 0],
            ["Tentativas enviadas",  (await db.execute(select(func.count(Attempt.id)).where(Attempt.status == AttemptStatus.SUBMITTED))).scalar() or 0],
            ["Interações tutor",     (await db.execute(select(func.count(TutorInteraction.id)))).scalar() or 0],
        ]

    elif report_type == "ai_usage":
        headers = ["ID", "Tipo", "User ID", "Criado em"]
        for t in (await db.execute(select(TutorInteraction).order_by(TutorInteraction.created_at.desc()).limit(5000))).scalars().all():
            rows.append([str(t.id), t.kind, str(t.user_id) if t.user_id else "",
                         t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else ""])

    elif report_type == "audit":
        headers = ["ID", "Ação", "Entidade", "Actor", "Criado em"]
        for l in (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(5000))).scalars().all():
            rows.append([str(l.id), l.action, l.entity,
                         str(l.actor_user_id) if l.actor_user_id else "",
                         l.created_at.strftime("%d/%m/%Y %H:%M") if l.created_at else ""])
    else:
        raise HTTPException(404, f"Relatório '{report_type}' não encontrado.")

    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL).writerows([headers, *rows])
    out.seek(0)
    fname = f"relatorio_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await audit(db, me.id, "ADMIN_EXPORT_REPORT", "Report", None, after={"type": report_type})
    await db.commit()
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )

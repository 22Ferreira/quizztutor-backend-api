import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import Class, ClassEnrollment, User, UserRole
from app.schemas.classes import ClassCreate, ClassOut, JoinClassRequest, InviteEmailsRequest, ClassUpdate, EnrollmentOut
from app.services.audit import audit

router = APIRouter(prefix="/classes", tags=["classes"])


def _code():
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10].upper()


@router.post("", response_model=ClassOut, dependencies=[Depends(require_roles("PROFESSOR"))])
async def create_class(payload: ClassCreate, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    c = Class(name=payload.name, discipline=payload.discipline if hasattr(payload, 'discipline') else None, professor_id=me.id, code_entry=_code())
    db.add(c)
    await audit(db, me.id, "CREATE_CLASS", "Class", c.id, after={"name": c.name})
    await db.commit()
    await db.refresh(c)
    return ClassOut(id=c.id, name=c.name, code_entry=c.code_entry, active=c.active, professor_id=c.professor_id, created_at=c.created_at)


@router.get("", response_model=list[ClassOut])
async def list_classes(db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    if me.role == UserRole.ADMIN:
        q = await db.execute(select(Class))
    elif me.role == UserRole.PROFESSOR:
        q = await db.execute(select(Class).where(Class.professor_id == me.id))
    elif me.role == UserRole.ALUNO:
        # Return classes the student belongs to
        enroll_q = await db.execute(select(ClassEnrollment).where(ClassEnrollment.user_id == me.id, ClassEnrollment.status == "ACTIVE"))
        class_ids = [e.class_id for e in enroll_q.scalars().all()]
        q = await db.execute(select(Class).where(Class.id.in_(class_ids)))
    else:
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = q.scalars().all()
    return [ClassOut(id=r.id, name=r.name, code_entry=r.code_entry, active=r.active, professor_id=r.professor_id, created_at=r.created_at) for r in rows]



@router.get("/my-invites")
async def my_invites(db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    """Return pending invitations for the logged-in student by their email."""
    invite_q = await db.execute(
        select(ClassEnrollment).where(
            ClassEnrollment.invited_email == me.email,
            ClassEnrollment.status == "INVITED"
        )
    )
    invites = invite_q.scalars().all()
    if not invites:
        return []

    # 1 query para todas as turmas de uma vez — sem N+1
    class_ids = [e.class_id for e in invites]
    classes_q = await db.execute(select(Class).where(Class.id.in_(class_ids)))
    classes_map = {c.id: c for c in classes_q.scalars().all()}

    result = []
    for e in invites:
        c = classes_map.get(e.class_id)
        if c:
            result.append({
                "enrollment_id": str(e.id),
                "class_id": str(c.id),
                "class_name": c.name,
                "discipline": c.discipline,
                "code_entry": c.code_entry,
                "invited_at": e.invited_at.isoformat() if e.invited_at else None,
            })
    return result


@router.post("/accept-invite/{enrollment_id}")
async def accept_invite(enrollment_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    """Accept a pending invitation by enrollment ID."""
    invite_q = await db.execute(
        select(ClassEnrollment).where(
            ClassEnrollment.id == enrollment_id,
            ClassEnrollment.invited_email == me.email,
            ClassEnrollment.status == "INVITED"
        )
    )
    e = invite_q.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    exists_q = await db.execute(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == e.class_id,
            ClassEnrollment.user_id == me.id,
            ClassEnrollment.status == "ACTIVE"
        )
    )
    if exists_q.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Já matriculado nesta turma")
    e.user_id = me.id
    e.status = "ACTIVE"
    e.joined_at = datetime.now(timezone.utc)
    await audit(db, me.id, "ACCEPT_INVITE", "ClassEnrollment", e.id, after={"class_id": str(e.class_id)})
    await db.commit()
    return {"message": "ok", "class_id": str(e.class_id)}


@router.get("/{class_id}", response_model=ClassOut)
async def get_class(class_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Class).where(Class.id == class_id))
    c = q.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    if me.role == UserRole.PROFESSOR and c.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return ClassOut(id=c.id, name=c.name, code_entry=c.code_entry, active=c.active, professor_id=c.professor_id, created_at=c.created_at)


@router.get("/{class_id}/students", response_model=list[EnrollmentOut])
async def list_students(class_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Class).where(Class.id == class_id))
    c = q.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    if me.role == UserRole.PROFESSOR and c.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    enroll_q = await db.execute(select(ClassEnrollment).where(ClassEnrollment.class_id == class_id))
    enrollments = enroll_q.scalars().all()
    return [
        EnrollmentOut(
            id=e.id,
            user_id=e.user_id,
            invited_email=e.invited_email,
            status=e.status,
            joined_at=e.joined_at,
            name=e.user.name if e.user else None,
            email=e.user.email if e.user else e.invited_email,
        )
        for e in enrollments
    ]



@router.get("/{class_id}/assignments")
async def list_class_assignments(class_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    """Return all active assignments for a class (used by students to see available quizzes)."""
    from app.models.assignment import Assignment, AssignmentType
    from app.models.quiz import Quiz, QuizStatus

    # Verify class exists and user has access
    class_q = await db.execute(select(Class).where(Class.id == class_id))
    c = class_q.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Turma não encontrada")

    # Students: must be enrolled; Professors: must own the class; Admin: free pass
    if me.role == UserRole.ALUNO:
        import uuid as _uuid2
        enroll_q = await db.execute(
            select(ClassEnrollment).where(
                ClassEnrollment.class_id == _uuid2.UUID(class_id),
                ClassEnrollment.user_id == me.id,
                ClassEnrollment.status == "ACTIVE"
            )
        )
        if not enroll_q.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Não matriculado nesta turma")
    elif me.role == UserRole.PROFESSOR and c.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    import uuid as _uuid
    # Get all CLASS-type assignments for this class
    # Use cast to UUID to avoid string/UUID mismatch
    try:
        class_uuid = _uuid.UUID(class_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="class_id inválido")

    assign_q = await db.execute(
        select(Assignment).where(
            Assignment.class_id == class_uuid,
            Assignment.type == AssignmentType.CLASS,
        )
    )
    assignments = assign_q.scalars().all()

    active_assignments = [a for a in assignments if a.active]
    if not active_assignments:
        return []

    # 1 query para todos os quizzes de uma vez — sem N+1
    quiz_ids = [a.quiz_id for a in active_assignments]
    quizzes_q = await db.execute(
        select(Quiz).where(
            Quiz.id.in_(quiz_ids),
            Quiz.status.in_([QuizStatus.PUBLISHED, QuizStatus.CLOSED]),
        )
    )
    quiz_map = {q.id: q for q in quizzes_q.scalars().all()}

    result = []
    for a in active_assignments:
        quiz = quiz_map.get(a.quiz_id)
        if not quiz:
            continue
        result.append({
            "id": str(a.id),
            "quiz_id": str(quiz.id),
            "quiz_title": quiz.title,
            "quiz_description": quiz.description or "",
            "type": a.type.value,
            "status": quiz.status.value,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
            "require_identity": a.require_identity,
        })
    return result

@router.post("/join", dependencies=[Depends(require_roles("ALUNO"))])
async def join(payload: JoinClassRequest, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Class).where(Class.code_entry == payload.code_entry))
    c = q.scalar_one_or_none()
    if not c or not c.active:
        raise HTTPException(status_code=404, detail="Turma inválida")
    exists = await db.execute(select(ClassEnrollment).where(ClassEnrollment.class_id == c.id, ClassEnrollment.user_id == me.id))
    e = exists.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if e:
        if e.status == "REMOVED":
            e.status = "ACTIVE"
            e.joined_at = now
            e.removed_at = None
        await db.commit()
        return {"message": "ok", "class_id": str(c.id), "class_name": c.name}
    db.add(ClassEnrollment(class_id=c.id, user_id=me.id, status="ACTIVE", joined_at=now))
    await audit(db, me.id, "JOIN_CLASS", "Class", c.id, after={"user_id": str(me.id)})
    await db.commit()
    return {"message": "ok", "class_id": str(c.id), "class_name": c.name}


@router.post("/{class_id}/invite", dependencies=[Depends(require_roles("PROFESSOR"))])
async def invite(class_id: str, payload: InviteEmailsRequest, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Class).where(Class.id == class_id))
    c = q.scalar_one_or_none()
    if not c or c.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    now = datetime.now(timezone.utc)
    added = []
    for em in payload.emails:
        exists = await db.execute(select(ClassEnrollment).where(ClassEnrollment.class_id == c.id, ClassEnrollment.invited_email == em))
        if exists.scalar_one_or_none():
            continue
        db.add(ClassEnrollment(class_id=c.id, invited_email=str(em), status="INVITED", invited_at=now))
        added.append(str(em))
    await audit(db, me.id, "INVITE_CLASS", "Class", c.id, after={"emails": added})
    await db.commit()
    return {"message": "invited", "added": added}


@router.delete("/{class_id}/students/{user_id}", dependencies=[Depends(require_roles("PROFESSOR"))])
async def remove_student(class_id: str, user_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Class).where(Class.id == class_id))
    c = q.scalar_one_or_none()
    if not c or c.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    eq = await db.execute(select(ClassEnrollment).where(ClassEnrollment.class_id == c.id, ClassEnrollment.user_id == user_id))
    e = eq.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Matrícula não encontrada")
    e.status = "REMOVED"
    e.removed_at = datetime.now(timezone.utc)
    await audit(db, me.id, "REMOVE_STUDENT", "ClassEnrollment", e.id, after={"user_id": user_id})
    await db.commit()
    return {"message": "ok"}

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import User, UserRole, Quiz, QuizStatus
from app.models.global_quiz import GlobalQuizRequest, GlobalQuizRequestStatus
from app.models.attempt import Attempt, AttemptOrigin, AttemptStatus
from app.models.quiz import QuizQuestion
from app.services.attempt_rules import calc_attempt_expiry

from app.schemas.global_quizzes import (
    GlobalSubmitOut,
    GlobalStatusOut,
    GlobalQuizListItem,
)
from app.schemas.attempts import AttemptOut
from app.services.audit import audit

router = APIRouter(tags=["global-quizzes"])


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return s[:40] if s else "quiz"


def _make_slug(title: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"{_slugify(title)}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{suffix}"


@router.post(
    "/quizzes/{quiz_id}/global/submit",
    response_model=GlobalSubmitOut,
    dependencies=[Depends(require_roles("PROFESSOR"))],
)
async def submit_global(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()

    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    if quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(
            status_code=400,
            detail="Apenas quizzes PUBLISHED podem solicitar publicação global",
        )

    rq = await db.execute(
        select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == quiz.id)
    )
    req = rq.scalar_one_or_none()

    if not req:
        req = GlobalQuizRequest(
            quiz_id=quiz.id,
            requested_by=me.id,
            status=GlobalQuizRequestStatus.PENDING,
            is_active=True,
        )
        db.add(req)
    else:
        req.status = GlobalQuizRequestStatus.PENDING
        req.is_active = True
        req.requested_by = me.id
        req.review_note = None
        req.reviewed_by = None
        req.reviewed_at = None
        req.approved_public_slug = None

    await audit(
        db,
        me.id,
        "GLOBAL_PUBLISH_REQUESTED",
        "Quiz",
        quiz.id,
        after={"status": "PENDING"},
    )

    await db.commit()
    await db.refresh(req)

    return GlobalSubmitOut(request_id=str(req.id), status=req.status)


@router.get(
    "/quizzes/{quiz_id}/global/status",
    response_model=GlobalStatusOut,
    dependencies=[Depends(require_roles("PROFESSOR", "ADMIN"))],
)
async def global_status(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    rq = await db.execute(
        select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == quiz.id)
    )
    req = rq.scalar_one_or_none()

    if not req:
        return GlobalStatusOut(status="NONE", is_active=False)

    return GlobalStatusOut(
        status=req.status,
        is_active=req.is_active,
        review_note=req.review_note,
        slug=req.approved_public_slug,
    )


@router.post(
    "/quizzes/{quiz_id}/global/revoke",
    response_model=GlobalStatusOut,
    dependencies=[Depends(require_roles("PROFESSOR"))],
)
async def revoke_global(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()

    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    rq = await db.execute(
        select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == quiz.id)
    )
    req = rq.scalar_one_or_none()

    if not req:
        raise HTTPException(
            status_code=404,
            detail="Nenhum pedido global para este quiz",
        )

    req.status = GlobalQuizRequestStatus.REVOKED
    req.is_active = False
    # Sem isso, uma nota antiga (de uma aprovação/rejeição anterior) ficava
    # "grudada" no pedido depois de revogado, mostrando um aviso que
    # contradizia o status atual (ex: nota falando em aprovação junto com
    # o badge "Revogado").
    req.review_note = None

    await audit(
        db,
        me.id,
        "GLOBAL_PUBLISH_REVOKED",
        "Quiz",
        quiz.id,
        after={"status": "REVOKED"},
    )

    await db.commit()

    return GlobalStatusOut(
        status=req.status,
        is_active=req.is_active,
        review_note=req.review_note,
        slug=req.approved_public_slug,
    )


@router.get("/global/quizzes", response_model=list[GlobalQuizListItem])
async def list_global_quizzes(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rq = await db.execute(
        select(GlobalQuizRequest, Quiz)
        .join(Quiz, Quiz.id == GlobalQuizRequest.quiz_id)
        .where(GlobalQuizRequest.status == GlobalQuizRequestStatus.APPROVED)
        .where(GlobalQuizRequest.is_active.is_(True))
    )

    items = []

    for req, quiz in rq.all():
        items.append(
            GlobalQuizListItem(
                slug=req.approved_public_slug,
                quiz_id=str(quiz.id),
                title=quiz.title,
                description=quiz.description,
                professor_id=str(quiz.professor_id),
                approved_at=req.reviewed_at,
                question_count=len(quiz.questions),
            )
        )

    return items


@router.get("/global/quizzes/{slug}", response_model=GlobalQuizListItem)
async def get_global_quiz(
    slug: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rq = await db.execute(
        select(GlobalQuizRequest, Quiz)
        .join(Quiz, Quiz.id == GlobalQuizRequest.quiz_id)
        .where(GlobalQuizRequest.approved_public_slug == slug)
        .where(GlobalQuizRequest.status == GlobalQuizRequestStatus.APPROVED)
        .where(GlobalQuizRequest.is_active.is_(True))
    )

    row = rq.first()

    if not row:
        raise HTTPException(status_code=404, detail="Não encontrado")

    req, quiz = row

    return GlobalQuizListItem(
        slug=req.approved_public_slug,
        quiz_id=str(quiz.id),
        title=quiz.title,
        description=quiz.description,
        professor_id=str(quiz.professor_id),
        approved_at=req.reviewed_at,
        question_count=len(quiz.questions),
    )


@router.post("/global/quizzes/{slug}/attempts/start", response_model=AttemptOut)
async def start_global_attempt(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rq = await db.execute(
        select(GlobalQuizRequest, Quiz)
        .join(Quiz, Quiz.id == GlobalQuizRequest.quiz_id)
        .where(GlobalQuizRequest.approved_public_slug == slug)
        .where(GlobalQuizRequest.status == GlobalQuizRequestStatus.APPROVED)
        .where(GlobalQuizRequest.is_active.is_(True))
    )

    row = rq.first()

    if not row:
        raise HTTPException(status_code=404, detail="Quiz global não encontrado")

    req, quiz = row

    if quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Quiz não disponível")

    now = datetime.now(timezone.utc)

    if quiz.availability_start and now < quiz.availability_start:
        raise HTTPException(status_code=400, detail="Questionário ainda não disponível")

    if quiz.availability_end and now > quiz.availability_end:
        raise HTTPException(status_code=400, detail="Questionário encerrado")

    qq = await db.execute(
        select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
    )
    questions = qq.scalars().all()

    if not questions:
        raise HTTPException(status_code=400, detail="Quiz sem questões")

    ordered = sorted(questions, key=lambda x: x.order)

    if quiz.shuffle_questions:
        import random
        random.shuffle(ordered)

    ordered_ids = [str(q.id) for q in ordered]
    score_max = sum(q.points for q in ordered)
    expires_at = calc_attempt_expiry(quiz)

    attempt = Attempt(
        quiz_id=quiz.id,
        assignment_id=None,
        class_id=None,
        participant_user_id=me.id,
        participant_email=me.email,
        participant_name=me.name,
        participant_role=me.role,
        origin=AttemptOrigin.GLOBAL,
        global_request_id=req.id,
        status=AttemptStatus.IN_PROGRESS,
        expires_at=expires_at,
        question_order_json=ordered_ids,
        score_max=score_max,
        score_obtained=0,
    )

    db.add(attempt)

    await audit(
        db,
        me.id,
        "START_GLOBAL_ATTEMPT",
        "Attempt",
        attempt.id,
        after={"quiz_id": str(quiz.id), "origin": "GLOBAL"},
    )

    await db.commit()
    await db.refresh(attempt)

    return AttemptOut.model_validate(attempt, from_attributes=True)
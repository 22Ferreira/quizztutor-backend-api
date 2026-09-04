import secrets
from pydantic import BaseModel
from typing import Optional
import random
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user, get_optional_user
from app.models import User, UserRole, Quiz, QuizStatus, QuizQuestion, QuizOption, TutorConfig, Assignment, AssignmentType, QuizInvite, PublicLink, Class
from app.schemas.quizzes import QuizCreate, QuizOut, QuizUpdate, AssignmentCreate, TutorConfigIn
from app.services.audit import audit
from app.services.quiz_rules import validate_publish

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.post("", response_model=QuizOut, dependencies=[Depends(require_roles("PROFESSOR"))])
async def create_quiz(payload: QuizCreate, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    # ─────────────────────────────────────────────────────────────
    # 1) Aceitar "quiz_type" do frontend como alias do seu "mode"
    # ─────────────────────────────────────────────────────────────
    quiz_mode = payload.mode
    frontend_quiz_type = getattr(payload, "quiz_type", None)
    if frontend_quiz_type:
        quiz_mode = frontend_quiz_type

    # ─────────────────────────────────────────────────────────────
    # 2) Aceitar "time_config" do frontend e mapear para colunas
    # ─────────────────────────────────────────────────────────────
    tempo_mode = payload.tempo_mode
    time_total_seconds = payload.time_total_seconds
    time_default_question_seconds = payload.time_default_question_seconds
    time_by_difficulty = payload.time_by_difficulty

    tc = getattr(payload, "time_config", None)
    if tc and isinstance(tc, dict):
        tc_mode = tc.get("mode")

        if tc_mode == "NONE":
            # Sem tempo: zera tudo
            tempo_mode = TempoMode.TOTAL
            time_total_seconds = None
            time_default_question_seconds = None
            time_by_difficulty = None

        elif tc_mode == "TOTAL":
            tempo_mode = TempoMode.TOTAL
            time_total_seconds = tc.get("total_sec")
            time_default_question_seconds = None
            time_by_difficulty = None

        elif tc_mode == "PER_QUESTION":
            tempo_mode = TempoMode.PER_QUESTION
            time_total_seconds = None
            time_default_question_seconds = tc.get("default_sec")
            time_by_difficulty = None

        elif tc_mode == "MIXED":
            tempo_mode = TempoMode.MIXED
            time_total_seconds = tc.get("total_sec")  # opcional
            time_default_question_seconds = tc.get("default_sec")  # opcional
            time_by_difficulty = {
                "FACIL": tc.get("easy_sec"),
                "MEDIA": tc.get("medium_sec"),
                "DIFICIL": tc.get("hard_sec"),
            }

    # ─────────────────────────────────────────────────────────────
    # 3) Criar quiz
    # ─────────────────────────────────────────────────────────────
    quiz = Quiz(
        professor_id=me.id,
        title=payload.title,
        description=payload.description,
        mode=quiz_mode,
        tempo_mode=tempo_mode,
        time_total_seconds=time_total_seconds,
        time_default_question_seconds=time_default_question_seconds,
        time_by_difficulty=time_by_difficulty,
        max_attempts=payload.max_attempts,
        shuffle_questions=payload.shuffle_questions,
        shuffle_options=payload.shuffle_options,
        hint_levels=payload.hint_levels,
        explanation_policy=payload.explanation_policy,
        tutor_active=payload.tutor_active,
        chat_active=payload.chat_active,
        show_correct_immediate=payload.show_correct_immediate,
        solutions_released=payload.solutions_released,
        availability_start=payload.availability_start,
        availability_end=payload.availability_end,
    )

    db.add(quiz)
    db.add(TutorConfig(quiz=quiz))

    # ─────────────────────────────────────────────────────────────
    # 4) Inserir questões aceitando:
    #    - order_index (frontend) OU order (backend)
    #    - time_override_sec (frontend) OU time_override_seconds (backend)
    #    - options sem order -> usa índice como order
    # ─────────────────────────────────────────────────────────────
    if getattr(payload, "questions", None):
        await db.flush()

        for qi, qin in enumerate(payload.questions):
            q_order = getattr(qin, "order", None)
            if q_order is None:
                q_order = getattr(qin, "order_index", qi)

            q_time_override = getattr(qin, "time_override_seconds", None)
            if q_time_override is None:
                q_time_override = getattr(qin, "time_override_sec", None)

            qq = QuizQuestion(
                quiz_id=quiz.id,
                order=q_order,
                type=getattr(qin, "type", "MCQ"),
                statement=qin.statement,
                explanation=getattr(qin, "explanation", None),
                difficulty=getattr(qin, "difficulty", None),
                points=getattr(qin, "points", 1),
                time_override_seconds=q_time_override,
                hint_1=getattr(qin, "hint_1", None),
                hint_2=getattr(qin, "hint_2", None),
                hint_3=getattr(qin, "hint_3", None),
                topic=getattr(qin, "topic", None),
                skill=getattr(qin, "skill", None),
                objective=getattr(qin, "objective", None),
                short_reference=getattr(qin, "short_reference", None),
                media_type=getattr(qin, "media_type", None),
                media_url=getattr(qin, "media_url", None),
                attachment_urls=getattr(qin, "attachment_urls", None) or [],
            )

            db.add(qq)
            await db.flush()

            for oi, oin in enumerate(getattr(qin, "options", []) or []):
                o_order = getattr(oin, "order", oi)
                db.add(
                    QuizOption(
                        question_id=qq.id,
                        order=o_order,
                        text=oin.text,
                        is_correct=getattr(oin, "is_correct", False),
                        justification=getattr(oin, "justification", None),
                    )
                )

    await audit(db, me.id, "CREATE_QUIZ", "Quiz", quiz.id, after={"title": quiz.title})
    await db.commit()

    q2 = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.id == quiz.id)
    )
    quiz = q2.scalar_one()
    return QuizOut.model_validate(quiz, from_attributes=True)


@router.get("", response_model=list[QuizOut])
async def list_quizzes(db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    """
    Lista quizzes com 1 query para quizzes+questões+opções (eager load)
    e 1 query para os GlobalQuizRequests recentes — sem N+1.
    """
    from app.models.global_quiz import GlobalQuizRequest, GlobalQuizRequestStatus
    from sqlalchemy import desc
    from sqlalchemy.orm import selectinload

    # 1 query trazendo tudo com eager load
    if me.role == UserRole.ADMIN:
        stmt = select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        )
    elif me.role == UserRole.PROFESSOR:
        stmt = select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.professor_id == me.id)
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    q = await db.execute(stmt)
    quizzes = q.scalars().unique().all()

    if not quizzes:
        return []

    # 1 query para os pedidos globais mais recentes de todos os quizzes
    quiz_ids = [qz.id for qz in quizzes]
    from sqlalchemy import func
    # Subquery: última requisição por quiz_id
    subq = (
        select(
            GlobalQuizRequest.quiz_id,
            func.max(GlobalQuizRequest.requested_at).label("max_req"),
        )
        .where(GlobalQuizRequest.quiz_id.in_(quiz_ids))
        .group_by(GlobalQuizRequest.quiz_id)
        .subquery()
    )
    gr_q = await db.execute(
        select(GlobalQuizRequest).join(
            subq,
            (GlobalQuizRequest.quiz_id == subq.c.quiz_id)
            & (GlobalQuizRequest.requested_at == subq.c.max_req),
        )
    )
    global_reqs = {str(r.quiz_id): r for r in gr_q.scalars().all()}

    # 1 query para contar tentativas submetidas por quiz — sem N+1
    from app.models.attempt import Attempt
    cnt_q = await db.execute(
        select(Attempt.quiz_id, func.count())
        .where(Attempt.quiz_id.in_(quiz_ids), Attempt.status == "SUBMITTED")
        .group_by(Attempt.quiz_id)
    )
    attempt_counts = {str(qid): count for qid, count in cnt_q.all()}

    result = []
    for quiz_obj in quizzes:
        out = QuizOut.model_validate(quiz_obj, from_attributes=True)
        req = global_reqs.get(str(quiz_obj.id))
        if req:
            out.global_status = req.status.value if hasattr(req.status, "value") else str(req.status)
            out.global_request_id = str(req.id)
        out.attempt_count = attempt_counts.get(str(quiz_obj.id), 0)
        result.append(out)
    return result





# ── Share code endpoints ──────────────────────────────────────────────────────

class QuizPreviewOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    question_count: int
    professor_name: Optional[str] = None
    share_code: str


@router.get("/code/{share_code}", response_model=QuizPreviewOut)
async def preview_by_code(
    share_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Public: preview a quiz by its share code (no auth required)."""
    from app.models.user import User as UserModel
    q = await db.execute(
        select(Quiz).options(selectinload(Quiz.questions))
        .where(Quiz.share_code == share_code.upper().strip())
        .where(Quiz.status == "PUBLISHED")
    )
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Código inválido ou quiz não encontrado.")

    prof_name = None
    u = await db.execute(select(UserModel).where(UserModel.id == quiz.professor_id))
    user = u.scalar_one_or_none()
    if user:
        prof_name = getattr(user, "name", None) or user.email

    return QuizPreviewOut(
        id=str(quiz.id),
        title=quiz.title,
        description=quiz.description,
        question_count=len(quiz.questions),
        professor_name=prof_name,
        share_code=quiz.share_code,
    )


@router.post("/code/{share_code}/start")
async def start_by_code(
    share_code: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    """Start an attempt via share code."""
    from app.models.assignment import Assignment, AssignmentType
    from app.models.attempt import Attempt, AttemptStatus

    q = await db.execute(
        select(Quiz).options(selectinload(Quiz.questions))
        .where(Quiz.share_code == share_code.upper().strip())
        .where(Quiz.status == "PUBLISHED")
    )
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Código inválido ou quiz não encontrado.")

    # Find or create a PUBLIC_LINK assignment as the shared pool for this code
    assign_q = await db.execute(
        select(Assignment).where(
            Assignment.quiz_id == quiz.id,
            Assignment.type == AssignmentType.PUBLIC_LINK,
            Assignment.class_id == None,
            Assignment.active == True,
        )
    )
    assignment = assign_q.scalars().first()
    if not assignment:
        assignment = Assignment(
            quiz_id=quiz.id,
            type=AssignmentType.PUBLIC_LINK,
            class_id=None,
            active=True,
            max_attempts=quiz.max_attempts,
            require_identity=True,
            allow_guest=False,
        )
        db.add(assignment)
        await db.flush()
    elif assignment.max_attempts != quiz.max_attempts:
        # Sincroniza com o quiz: se o professor alterou max_attempts, reflete aqui
        assignment.max_attempts = quiz.max_attempts
        await db.flush()

    if me:
        count_q = await db.execute(
            select(Attempt).where(
                Attempt.assignment_id == assignment.id,
                Attempt.participant_user_id == me.id,
            )
        )
        existing = count_q.scalars().all()
        if len(existing) >= assignment.max_attempts:
            raise HTTPException(status_code=429, detail=f"Limite de {assignment.max_attempts} tentativa(s) atingido.")
        in_prog = [a for a in existing if str(a.status) in ("IN_PROGRESS", "AttemptStatus.IN_PROGRESS")]
        if in_prog:
            return {"id": str(in_prog[-1].id)}

    question_ids = [str(q.id) for q in quiz.questions]
    attempt = Attempt(
        assignment_id=assignment.id,
        quiz_id=quiz.id,
        participant_user_id=me.id if me else None,
        participant_email=me.email if me else None,
        status=AttemptStatus.IN_PROGRESS,
        question_order_json=question_ids,
        score_max=len(question_ids),
        score_obtained=0,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return {"id": str(attempt.id)}

@router.get("/{quiz_id}", response_model=QuizOut)
async def get_quiz(quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.id == quiz_id)
    )
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Not found")
    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return QuizOut.model_validate(quiz, from_attributes=True)


@router.put("/{quiz_id}", response_model=QuizOut, dependencies=[Depends(require_roles("PROFESSOR"))])
async def update_quiz(quiz_id: str, payload: QuizUpdate, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    if quiz.status not in (QuizStatus.DRAFT, QuizStatus.PUBLISHED):
        raise HTTPException(status_code=400, detail="Apenas quizzes em rascunho ou publicados podem ser editados")
    before = {"title": quiz.title, "description": quiz.description}
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k != "questions":
            setattr(quiz, k, v)
    if payload.questions is not None:
        # Busca IDs de questões que têm tentativas referenciando (não podem ser deletadas)
        from app.models.attempt import AttemptQuestionState
        referenced_q = await db.execute(
            select(AttemptQuestionState.question_id).join(
                QuizQuestion, QuizQuestion.id == AttemptQuestionState.question_id
            ).where(QuizQuestion.quiz_id == quiz.id).distinct()
        )
        referenced_ids = {row[0] for row in referenced_q.all()}

        # IDs das questões que o payload está enviando (questões existentes têm id)
        incoming_ids = {qin.id for qin in payload.questions if getattr(qin, "id", None)}

        # Deletar apenas questões que NÃO têm referências em tentativas e NÃO estão no payload
        existing_q = await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
        existing_questions = existing_q.scalars().all()
        for eq in existing_questions:
            if eq.id not in incoming_ids and eq.id not in referenced_ids:
                # Seguro deletar: sem referências e removida do payload
                await db.execute(delete(QuizOption).where(QuizOption.question_id == eq.id))
                await db.execute(delete(QuizQuestion).where(QuizQuestion.id == eq.id))

        await db.flush()

        for qin in payload.questions:
            qin_id = getattr(qin, "id", None)
            if qin_id:
                # Atualizar questão existente (upsert)
                eq_r = await db.execute(select(QuizQuestion).where(QuizQuestion.id == qin_id))
                eq = eq_r.scalar_one_or_none()
                if eq:
                    eq.order = qin.order
                    eq.type = qin.type
                    eq.statement = qin.statement
                    eq.explanation = qin.explanation
                    eq.difficulty = qin.difficulty
                    eq.points = qin.points
                    eq.time_override_seconds = qin.time_override_seconds
                    eq.hint_1 = qin.hint_1
                    eq.hint_2 = qin.hint_2
                    eq.hint_3 = qin.hint_3
                    eq.topic = qin.topic
                    eq.skill = qin.skill
                    eq.objective = qin.objective
                    eq.short_reference = qin.short_reference
                    eq.media_type = getattr(qin, "media_type", None)
                    eq.media_url = getattr(qin, "media_url", None)
                    eq.attachment_urls = getattr(qin, "attachment_urls", None) or []
                    # Atualizar opções: deletar e recriar (options não têm referências diretas em attempts)
                    await db.execute(delete(QuizOption).where(QuizOption.question_id == eq.id))
                    await db.flush()
                    for oin in qin.options:
                        db.add(QuizOption(
                            question_id=eq.id,
                            order=oin.order,
                            text=oin.text,
                            is_correct=oin.is_correct,
                            justification=oin.justification,
                        ))
                    continue

            # Nova questão (sem id ou id não encontrado)
            qq = QuizQuestion(
                quiz_id=quiz.id,
                order=qin.order,
                type=qin.type,
                statement=qin.statement,
                explanation=qin.explanation,
                difficulty=qin.difficulty,
                points=qin.points,
                time_override_seconds=qin.time_override_seconds,
                hint_1=qin.hint_1,
                hint_2=qin.hint_2,
                hint_3=qin.hint_3,
                topic=qin.topic,
                skill=qin.skill,
                objective=qin.objective,
                short_reference=qin.short_reference,
                media_type=getattr(qin, "media_type", None),
                media_url=getattr(qin, "media_url", None),
                attachment_urls=getattr(qin, "attachment_urls", None) or [],
            )
            db.add(qq)
            await db.flush()
            for oin in qin.options:
                db.add(QuizOption(
                    question_id=qq.id,
                    order=oin.order,
                    text=oin.text,
                    is_correct=oin.is_correct,
                    justification=oin.justification,
                ))
    await audit(db, me.id, "UPDATE_QUIZ", "Quiz", quiz.id, before=before, after=payload.model_dump(exclude_unset=True, mode="json"))
    await db.commit()
    # Re-fetch with eager loading to avoid MissingGreenlet on lazy relationships
    q2 = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.id == quiz.id)
    )
    quiz = q2.scalar_one()
    return QuizOut.model_validate(quiz, from_attributes=True)


@router.post("/{quiz_id}/publish", dependencies=[Depends(require_roles("PROFESSOR"))])
async def publish(quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    if quiz.status == QuizStatus.PUBLISHED:
        return {"message": "already_published"}
    if quiz.status not in (QuizStatus.DRAFT, QuizStatus.PUBLISHED):
        raise HTTPException(status_code=400, detail="Status inválido")
    validate_publish(quiz)
    quiz.status = QuizStatus.PUBLISHED
    if not quiz.share_code:
        import secrets as _sec
        quiz.share_code = _sec.token_hex(4).upper()
    await audit(db, me.id, "PUBLISH_QUIZ", "Quiz", quiz.id, before={"status": "DRAFT"}, after={"status": "PUBLISHED"})
    await db.commit()
    return {"message": "published"}


@router.post("/{quiz_id}/close", dependencies=[Depends(require_roles("PROFESSOR", "ADMIN"))])
async def close(quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Not found")
    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    quiz.status = QuizStatus.CLOSED
    await audit(db, me.id, "CLOSE_QUIZ", "Quiz", quiz.id, after={"status": "CLOSED"})
    await db.commit()
    return {"message": "closed"}


@router.post("/{quiz_id}/archive", dependencies=[Depends(require_roles("PROFESSOR"))])
async def archive(quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    quiz.status = QuizStatus.ARCHIVED
    await audit(db, me.id, "ARCHIVE_QUIZ", "Quiz", quiz.id, after={"status": "ARCHIVED"})
    await db.commit()
    return {"message": "archived"}


@router.post("/{quiz_id}/assignments", dependencies=[Depends(require_roles("PROFESSOR"))])
async def create_assignment(quiz_id: str, payload: AssignmentCreate, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    if quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Quiz deve estar PUBLISHED para criar atribuições")
    at = AssignmentType(payload.type)
    if at == AssignmentType.CLASS:
        if not payload.class_id:
            raise HTTPException(status_code=400, detail="class_id obrigatório")
        cq = await db.execute(select(Class).where(Class.id == payload.class_id))
        c = cq.scalar_one_or_none()
        if not c or c.professor_id != me.id:
            raise HTTPException(status_code=404, detail="Turma não encontrada")
        # Verifica se já existe atribuição ativa para esse quiz + turma
        dup_q = await db.execute(
            select(Assignment).where(
                Assignment.quiz_id == quiz.id,
                Assignment.type == AssignmentType.CLASS,
                Assignment.class_id == c.id,
                Assignment.active == True,
            )
        )
        if dup_q.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Já existe uma atribuição ativa para este quiz nesta turma.")
        a = Assignment(quiz_id=quiz.id, type=at, class_id=c.id, expires_at=payload.expires_at, require_identity=payload.require_identity, allow_guest=payload.allow_guest, max_attempts=payload.max_attempts, tutor_active_override=payload.tutor_active_override, show_correct_immediate_override=payload.show_correct_immediate_override, practice_mode=payload.practice_mode)
        db.add(a)
    elif at == AssignmentType.EMAIL_LIST:
        if not payload.emails:
            raise HTTPException(status_code=400, detail="emails obrigatório")
        a = Assignment(quiz_id=quiz.id, type=at, expires_at=payload.expires_at, require_identity=True, allow_guest=False)
        db.add(a)
        await db.flush()
        for em in payload.emails:
            db.add(QuizInvite(assignment_id=a.id, email=em))
    else:  # PUBLIC_LINK
        dup_pl = await db.execute(
            select(Assignment).where(
                Assignment.quiz_id == quiz.id,
                Assignment.type == AssignmentType.PUBLIC_LINK,
                Assignment.active == True,
            )
        )
        if dup_pl.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Já existe um link público ativo para este quiz.")
        a = Assignment(quiz_id=quiz.id, type=at, expires_at=payload.expires_at, require_identity=payload.require_identity, allow_guest=payload.allow_guest, max_attempts=payload.max_attempts)
        db.add(a)
        await db.flush()
        db.add(PublicLink(assignment_id=a.id, allow_guest=payload.allow_guest, require_identity=payload.require_identity, expires_at=payload.expires_at))
    await audit(db, me.id, "CREATE_ASSIGNMENT", "Assignment", None, after=payload.model_dump(mode="json"))
    await db.commit()
    await db.refresh(a)
    return {"message": "ok", "assignment_id": str(a.id)}


@router.get("/{quiz_id}/assignments")
async def list_assignments(quiz_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Not found")
    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    aq = await db.execute(select(Assignment).where(Assignment.quiz_id == quiz.id))
    assignments = aq.scalars().all()
    result = []
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for a in assignments:
        if not a.active:
            status = "REVOKED"
        elif a.expires_at and a.expires_at < now:
            status = "EXPIRED"
        else:
            status = "ACTIVE"

        target_label = None
        if a.type == AssignmentType.CLASS and a.classroom:
            target_label = a.classroom.name

        d = {
            "id": str(a.id),
            "type": a.type.value,
            "origin": a.type.value,
            "active": a.active,
            "status": status,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "class_id": str(a.class_id) if a.class_id else None,
            "target_label": target_label,
            "require_identity": a.require_identity,
            "max_attempts": a.max_attempts,
            "quiz_max_attempts": quiz.max_attempts if hasattr(quiz, 'max_attempts') else 1,
            "tutor_active_override": a.tutor_active_override,
            "show_correct_immediate_override": a.show_correct_immediate_override,
        }
        if a.public_links:
            d["public_token"] = a.public_links[0].token
        result.append(d)
    return result


class AssignmentOverridePayload(BaseModel):
    max_attempts: Optional[int] = None
    tutor_active_override: Optional[bool] = None
    show_correct_immediate_override: Optional[bool] = None
    practice_mode: Optional[bool] = None

@router.patch("/{quiz_id}/assignments/{assignment_id}")
async def patch_assignment(
    quiz_id: str, assignment_id: str,
    payload: AssignmentOverridePayload,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user)
):
    """Update override settings on an assignment (tutor, gabarito, max_attempts)."""
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    aq = await db.execute(
        select(Assignment).where(
            Assignment.id == assignment_id,
            Assignment.quiz_id == quiz.id,
        )
    )
    a = aq.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Atribuição não encontrada")

    if payload.max_attempts is not None:
        a.max_attempts = payload.max_attempts
    a.tutor_active_override = payload.tutor_active_override
    a.show_correct_immediate_override = payload.show_correct_immediate_override
    a.practice_mode = payload.practice_mode

    await db.commit()
    return {"message": "ok"}

@router.delete("/{quiz_id}/assignments/{assignment_id}", dependencies=[Depends(require_roles("PROFESSOR"))])
async def revoke_assignment(quiz_id: str, assignment_id: str, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    aq = await db.execute(
        select(Assignment).where(
            Assignment.id == assignment_id,
            Assignment.quiz_id == quiz.id,
        )
    )
    a = aq.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Atribuição não encontrada")
    a.active = False
    await audit(db, me.id, "REVOKE_ASSIGNMENT", "Assignment", a.id, after={"active": False})
    await db.commit()
    return {"message": "ok"}


@router.post("/{quiz_id}/tutor-config", dependencies=[Depends(require_roles("PROFESSOR"))])
async def set_tutor_config(quiz_id: str, payload: TutorConfigIn, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = q.scalar_one_or_none()
    if not quiz or quiz.professor_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    tc = quiz.tutor_config
    if not tc:
        tc = TutorConfig(quiz_id=quiz.id)
        db.add(tc)
    before = {"enabled": tc.enabled, "scope": tc.scope.value}
    tc.enabled = payload.enabled
    tc.scope = payload.scope
    tc.allow_out_of_scope = payload.allow_out_of_scope
    tc.allow_explanation = payload.allow_explanation
    tc.allow_hints = payload.allow_hints
    tc.system_prompt = payload.system_prompt
    await audit(db, me.id, "SET_TUTOR_CONFIG", "TutorConfig", tc.id, before=before, after=payload.model_dump(mode="json"))
    await db.commit()
    return {"message": "ok"}
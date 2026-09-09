import random
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.utils.rbac import get_current_user, get_optional_user
from app.utils.rate_limit import rate_limiter
from app.config import settings
from app.models import User
from app.models.quiz import Quiz, QuizStatus, TempoMode, QuizQuestion, QuizOption
from app.models.assignment import Assignment, PublicLink, QuizInvite
from app.models.attempt import Attempt, AttemptStatus, AttemptOrigin, AttemptQuestionState, Answer
from app.models.audit import EventLog
from app.schemas.attempts import (
    StartAttemptRequest, AttemptOut, CurrentQuestionOut, AnswerRequest, SubmitResponse,
    PauseExtendRequest, PauseExtendResponse,
)
from app.services.attempt_rules import ensure_attempt_active, calc_attempt_expiry
from app.services.audit import audit, event, _bg_event, _bg_audit
from app.services.quiz_rules import resolve_question_time, effective_time_config

router = APIRouter(prefix="/attempts", tags=["attempts"])

# Tolerância pro corte de prazo por questão — sem isso, uma resposta clicada
# a poucos milissegundos do fim chega ao servidor já depois do deadline por
# causa da latência de rede, e o aluno vê "esgotado" mesmo respondendo antes
# do cronômetro zerar na tela dele.
ANSWER_GRACE = timedelta(seconds=2)


async def _resolve_participant(
    payload: StartAttemptRequest,
    me: User | None,
    db: AsyncSession,
):
    """Return (user_id, participant_email, participant_name)."""
    if me:
        return str(me.id), me.email, me.name
    if payload.guest_name and payload.guest_email:
        return None, payload.guest_email, payload.guest_name
    raise HTTPException(status_code=400, detail="Autenticação ou dados de convidado obrigatórios")


@router.post("/start", response_model=AttemptOut)
async def start_attempt(
    payload: StartAttemptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    import logging
    logger = logging.getLogger("attempts.start")
    logger.info(f"[START] payload={payload.model_dump()} user={me.id if me else None}")
    ip = request.client.host if request.client else "unknown"
    key = str(me.id) if me else (payload.guest_email or ip)
    if not rate_limiter.hit(key, "start_attempt", settings.RL_ATTEMPT_START_PER_MIN):
        raise HTTPException(status_code=429, detail="Too many requests")

    # Resolve assignment/quiz
    assignment: Assignment | None = None
    quiz: Quiz | None = None
    if payload.public_token:
        pl_q = await db.execute(select(PublicLink).where(PublicLink.token == payload.public_token))
        pl = pl_q.scalar_one_or_none()
        if not pl:
            raise HTTPException(status_code=404, detail="Link público inválido")
        if pl.expires_at and datetime.now(timezone.utc) >= pl.expires_at:
            raise HTTPException(status_code=400, detail="Link expirado")
        assignment_q = await db.execute(select(Assignment).where(Assignment.id == pl.assignment_id))
        assignment = assignment_q.scalar_one_or_none()
    elif payload.assignment_id:
        assignment_q = await db.execute(select(Assignment).where(Assignment.id == payload.assignment_id))
        assignment = assignment_q.scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="assignment_id ou public_token obrigatório")
    if not assignment or not assignment.active:
        logger.warning(f"[START] assignment not found or inactive: id={payload.assignment_id} active={assignment.active if assignment else None}")
        raise HTTPException(status_code=404, detail="Atribuição não encontrada ou inativa")
    if assignment.expires_at and datetime.now(timezone.utc) >= assignment.expires_at:
        logger.warning(f"[START] assignment expired: expires_at={assignment.expires_at}")
        raise HTTPException(status_code=400, detail="Atribuição expirada")

    quiz_q = await db.execute(select(Quiz).where(Quiz.id == assignment.quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz or quiz.status != QuizStatus.PUBLISHED:
        logger.warning(f"[START] quiz not available: quiz={quiz.id if quiz else None} status={quiz.status if quiz else None}")
        raise HTTPException(status_code=400, detail="Questionário não disponível")
    # Availability window
    now = datetime.now(timezone.utc)
    if quiz.availability_start and now < quiz.availability_start:
        logger.warning(f"[START] quiz not yet available: availability_start={quiz.availability_start}")
        raise HTTPException(status_code=400, detail="Questionário ainda não disponível")
    if quiz.availability_end and now > quiz.availability_end:
        logger.warning(f"[START] quiz ended: availability_end={quiz.availability_end}")
        raise HTTPException(status_code=400, detail="Questionário encerrado")

    # Participant
    user_id, part_email, part_name = await _resolve_participant(payload, me, db)
    if user_id:
        count_filter = (
            Attempt.quiz_id == quiz.id,
            Attempt.participant_user_id == user_id,
            Attempt.status.in_(["SUBMITTED", "EXPIRED"]),
        )
    else:
        count_filter = (
            Attempt.quiz_id == quiz.id,
            Attempt.participant_email == part_email,
            Attempt.status.in_(["SUBMITTED", "EXPIRED"]),
        )
    # Scope count to current assignment so re-assigning resets the limit
    if assignment is not None:
        count_filter = count_filter + (Attempt.assignment_id == assignment.id,)
    count_q = await db.execute(select(func.count()).where(*count_filter))
    done = count_q.scalar() or 0
    max_attempts = getattr(assignment, 'max_attempts', None) or quiz.max_attempts
    logger.info(f"[START] done={done} max_attempts={max_attempts} quiz_id={quiz.id}")
    if done >= max_attempts:
        logger.warning(f"[START] max attempts reached: done={done} max={max_attempts}")
        raise HTTPException(status_code=400, detail="Limite de tentativas atingido")

    # Verificar se já existe tentativa IN_PROGRESS para este quiz
    if user_id:
        prog_filter = (
            Attempt.quiz_id == quiz.id,
            Attempt.participant_user_id == user_id,
            Attempt.status == "IN_PROGRESS",
        )
    else:
        prog_filter = (
            Attempt.quiz_id == quiz.id,
            Attempt.participant_email == part_email,
            Attempt.status == "IN_PROGRESS",
        )
    prog_q = await db.execute(select(Attempt).where(*prog_filter).order_by(Attempt.started_at.desc()).limit(1))
    existing = prog_q.scalars().first()
    if existing:
        # Retornar a tentativa existente em vez de criar nova
        return AttemptOut(
            id=existing.id,
            quiz_id=existing.quiz_id,
            status=existing.status.value,
            started_at=existing.started_at,
            expires_at=existing.expires_at,
            score_max=existing.score_max,
            score_obtained=existing.score_obtained,
        )

    # Build question order
    questions = list(quiz.questions)
    ordered_ids = [str(q.id) for q in sorted(questions, key=lambda x: x.order)]
    # randomize if needed (quiz doesn't store shuffle flag in this model; keep ordered)

    score_max = sum(q.points for q in questions)
    expires_at = calc_attempt_expiry(quiz, assignment)

    origin = AttemptOrigin.CLASS
    if payload.public_token:
        origin = AttemptOrigin.PUBLIC_LINK
    else:
        try:
            if hasattr(assignment, 'type') and str(assignment.type) == 'EMAIL_LIST':
                origin = AttemptOrigin.EMAIL
        except Exception:
            pass

    attempt = Attempt(
        quiz_id=quiz.id,
        assignment_id=assignment.id,
        participant_user_id=user_id,
        participant_email=part_email,
        participant_name=part_name,
        participant_role=(me.role if me else None),
        origin=origin,
        status=AttemptStatus.IN_PROGRESS,
        expires_at=expires_at,
        question_order_json=ordered_ids,
        score_max=score_max,
        score_obtained=0,
    )
    db.add(attempt)
    await db.flush()
    await event(db, user_id, "ATTEMPT_STARTED", {"quiz_id": str(quiz.id), "attempt_id": str(attempt.id)})
    await db.commit()
    await db.refresh(attempt)

    return AttemptOut(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        status=attempt.status.value,
        started_at=attempt.started_at,
        expires_at=attempt.expires_at,
        score_max=attempt.score_max,
        score_obtained=attempt.score_obtained,
    )


@router.get("/{attempt_id}/current-question", response_model=CurrentQuestionOut)
async def current_question(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_active(attempt)

    order = attempt.question_order_json
    # Find next unanswered
    answered_q = await db.execute(
        select(Answer.question_id).where(Answer.attempt_id == attempt.id)
    )
    answered_ids = {str(r) for r in answered_q.scalars().all()}

    # Auto-finaliza como "tempo esgotado" qualquer questão (modo PER_QUESTION/
    # MIXED) cujo prazo já passou sem resposta. Sem isso, o timeout de UMA
    # questão deixava o aluno preso nela pra sempre — o frontend só sabia
    # encerrar a tentativa INTEIRA ao ver o timer zerar, mesmo faltando
    # questões. Agora a questão vencida é marcada como errada/sem resposta
    # e a próxima é servida normalmente.
    now_check = datetime.now(timezone.utc)
    states_q = await db.execute(
        select(AttemptQuestionState).where(AttemptQuestionState.attempt_id == attempt.id)
    )
    states_by_qid = {str(s.question_id): s for s in states_q.scalars().all()}
    any_timed_out = False
    for qid in order:
        if qid in answered_ids:
            continue
        st = states_by_qid.get(qid)
        if st and st.question_deadline_at and now_check >= st.question_deadline_at + ANSWER_GRACE:
            db.add(Answer(
                attempt_id=attempt.id,
                question_id=qid,
                selected_option_id=None,
                text_answer=None,
                is_correct=False,
                points_awarded=0,
                practice_retries=0,
            ))
            answered_ids.add(qid)
            any_timed_out = True
    if any_timed_out:
        await db.commit()

    current_q_id = None
    current_idx = 0
    for idx, qid in enumerate(order):
        if qid not in answered_ids:
            current_q_id = qid
            current_idx = idx
            break

    if not current_q_id:
        raise HTTPException(status_code=400, detail="Todas as questões respondidas. Envie a tentativa.")

    qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id == current_q_id))
    qq = qq_q.scalar_one_or_none()
    if not qq:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    # State for this question
    state_q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt.id,
            AttemptQuestionState.question_id == qq.id,
        )
    )
    state = state_q.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    # Fetch assignment (se houver) uma vez só — usado tanto pro deadline da
    # questão quanto pros demais overrides de turma abaixo.
    asgn = None
    if attempt.assignment_id:
        asgn_q = await db.execute(select(Assignment).where(Assignment.id == attempt.assignment_id))
        asgn = asgn_q.scalar_one_or_none()

    quiz_meta_q = await db.execute(select(Quiz).where(Quiz.id == attempt.quiz_id))
    quiz_meta = quiz_meta_q.scalar_one_or_none()

    if not state:
        # O prazo NÃO é fixado aqui — só o instante em que a questão foi
        # aberta (opened_at). O deadline real só é calculado quando o
        # frontend confirma, via /start-timer, que a questão já está na
        # tela: se fixássemos agora, uma conexão lenta (ou VPS momentaneamente
        # devagar) descontaria do aluno o tempo de ida-e-volta da rede antes
        # dele sequer conseguir ler a pergunta.
        state = AttemptQuestionState(
            attempt_id=attempt.id,
            question_id=qq.id,
            opened_at=now,
            question_deadline_at=None,
        )
        db.add(state)
        attempt.last_activity_at = now
        await db.commit()
        await db.refresh(state)

    # Duração total, pra o frontend saber quanto pedir no /start-timer e
    # montar o círculo/label — sem fixar o prazo em si.
    time_allotted = None
    if quiz_meta:
        mode, _, _, _ = effective_time_config(quiz_meta, asgn)
        if mode in ("PER_QUESTION", "MIXED"):
            time_allotted = resolve_question_time(quiz_meta, qq, asgn)

    # Build options (hide is_correct if evaluation mode - handled later by quiz mode)
    options = [
        {"id": str(o.id), "text": o.text, "order": o.order}
        for o in sorted(qq.options, key=lambda x: x.order)
    ]

    # Apply assignment overrides if present
    show_correct = quiz_meta.show_correct_immediate if quiz_meta else True
    tutor_active = quiz_meta.tutor_active if quiz_meta else False
    practice_mode = False
    if asgn:
        if asgn.show_correct_immediate_override is not None:
            show_correct = asgn.show_correct_immediate_override
        if asgn.tutor_active_override is not None:
            tutor_active = asgn.tutor_active_override
        if asgn.practice_mode:
            practice_mode = True

    return CurrentQuestionOut(
        question_id=qq.id,
        order_index=current_idx,
        statement=qq.statement,
        type=qq.type,
        options=options,
        deadline_at=state.question_deadline_at,
        time_allotted_seconds=time_allotted,
        attempt_expires_at=attempt.expires_at,
        hints_used=state.hints_used,
        total_questions=len(order),
        quiz_title=quiz_meta.title if quiz_meta else None,
        show_correct_immediate=show_correct,
        tutor_active=tutor_active,
        practice_mode=practice_mode,
        media_type=qq.media_type,
        media_url=qq.media_url,
        attachment_urls=qq.attachment_urls or [],
        short_reference=qq.short_reference,
    )


@router.post("/{attempt_id}/questions/{question_id}/start-timer", response_model=PauseExtendResponse)
async def start_question_timer(
    attempt_id: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    """Fixa o prazo da questão só agora — quando o frontend confirma que já
    recebeu e renderizou a pergunta — em vez de no instante em que o GET
    current-question foi processado. Sem isso, o tempo de ida-e-volta da
    rede (ou uma VPS momentaneamente devagar) descontava do aluno uma fatia
    do prazo antes dele sequer conseguir ler a questão. Idempotente: se o
    prazo já foi fixado (segunda chamada, ex. de um reload), só devolve o
    que já está salvo, sem reiniciar a contagem."""
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_active(attempt)

    state_q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt.id,
            AttemptQuestionState.question_id == question_id,
        )
    )
    state = state_q.scalar_one_or_none()
    if not state:
        raise HTTPException(status_code=404, detail="Questão não iniciada")

    if state.question_deadline_at is None:
        qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id == question_id))
        qq = qq_q.scalar_one_or_none()
        quiz_q = await db.execute(select(Quiz).where(Quiz.id == attempt.quiz_id))
        quiz = quiz_q.scalar_one_or_none()
        asgn = None
        if attempt.assignment_id:
            asgn_q = await db.execute(select(Assignment).where(Assignment.id == attempt.assignment_id))
            asgn = asgn_q.scalar_one_or_none()
        if qq and quiz:
            mode, _, _, _ = effective_time_config(quiz, asgn)
            if mode in ("PER_QUESTION", "MIXED"):
                seconds = resolve_question_time(quiz, qq, asgn)
                state.question_deadline_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
                await db.commit()
                await db.refresh(state)

    return PauseExtendResponse(deadline_at=state.question_deadline_at)


@router.post("/{attempt_id}/answer")
async def submit_answer(
    attempt_id: str,
    payload: AnswerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_active(attempt)

    # Check question is in this attempt
    if str(payload.question_id) not in attempt.question_order_json:
        raise HTTPException(status_code=400, detail="Questão não pertence a esta tentativa")

    # Already answered?
    existing_q = await db.execute(
        select(Answer).where(Answer.attempt_id == attempt.id, Answer.question_id == payload.question_id)
    )
    if existing_q.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Questão já respondida")

    # Check question deadline if PER_QUESTION
    state_q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt.id,
            AttemptQuestionState.question_id == payload.question_id,
        )
    )
    state = state_q.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if state and state.question_deadline_at and now >= state.question_deadline_at + ANSWER_GRACE:
        raise HTTPException(status_code=400, detail="Tempo da questão esgotado")

    qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id == payload.question_id))
    qq = qq_q.scalar_one_or_none()
    if not qq:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    # Evaluate
    is_correct = None
    points_awarded = 0
    selected_option = None

    if payload.selected_option_id:
        opt_q = await db.execute(select(QuizOption).where(QuizOption.id == payload.selected_option_id))
        selected_option = opt_q.scalar_one_or_none()
        if not selected_option or selected_option.question_id != qq.id:
            raise HTTPException(status_code=400, detail="Alternativa inválida")
        is_correct = selected_option.is_correct
        if is_correct:
            points_awarded = qq.points
    elif payload.text_answer is not None:
        # SHORT_TEXT: professor reviews manually, mark None
        is_correct = None
        points_awarded = 0

    # ── Carregar quiz + assignment ANTES de salvar (necessário para practice_mode) ──
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == attempt.quiz_id))
    quiz = quiz_q.scalar_one_or_none()

    _show_correct = quiz.show_correct_immediate if quiz else False
    _practice_mode = False
    if attempt.assignment_id:
        from app.models.assignment import Assignment as _Asgn
        _asgn_q = await db.execute(select(_Asgn).where(_Asgn.id == attempt.assignment_id))
        _asgn = _asgn_q.scalar_one_or_none()
        if _asgn:
            if _asgn.show_correct_immediate_override is not None:
                _show_correct = _asgn.show_correct_immediate_override
            if _asgn.practice_mode:
                _practice_mode = True

    # ── Modo Prática: resposta errada sem skip → NÃO salva, retorna can_retry ──
    if _practice_mode and is_correct is False and not payload.skip:
        # Coleta dicas progressivas cadastradas na questão (hint_1 → hint_2 → hint_3)
        # explanation NÃO é incluída pois costuma revelar a resposta correta
        practice_hints = [h for h in [qq.hint_1, qq.hint_2, qq.hint_3] if h]
        if not practice_hints:
            practice_hints = ["Analise as alternativas e tente outra opção."]
        return {
            "can_retry": True,
            "is_correct": False,
            "hints": practice_hints,
        }

    # ── Salvar resposta (só chega aqui se: correto, skip, ou não é modo prática) ──
    answer = Answer(
        attempt_id=attempt.id,
        question_id=qq.id,
        selected_option_id=payload.selected_option_id,
        text_answer=payload.text_answer,
        is_correct=is_correct,
        points_awarded=points_awarded,
        practice_retries=payload.practice_retries,
    )
    db.add(answer)
    attempt.score_obtained += points_awarded
    attempt.last_activity_at = now
    await db.commit()
    background_tasks.add_task(
        _bg_event,
        str(attempt.participant_user_id) if attempt.participant_user_id else None,
        "ANSWER_SUBMITTED",
        {"attempt_id": str(attempt.id), "question_id": str(qq.id), "correct": is_correct},
    )

    # ── Montar resposta com feedback ──
    resp: dict = {"message": "ok", "is_correct": None, "explanation": None, "correct_option_id": None, "can_retry": False}
    # Mostrar feedback se show_correct_immediate OU modo prática (sempre mostra após resposta final)
    if is_correct is not None and (_show_correct or _practice_mode):
        resp["is_correct"] = is_correct
        resp["explanation"] = qq.explanation
        if not is_correct:
            correct_opts = [o for o in qq.options if o.is_correct]
            resp["correct_option_id"] = str(correct_opts[0].id) if correct_opts else None
    return resp


@router.post("/{attempt_id}/hint")
async def use_hint(
    attempt_id: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_active(attempt)

    qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id == question_id))
    qq = qq_q.scalar_one_or_none()
    if not qq:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    state_q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt.id,
            AttemptQuestionState.question_id == qq.id,
        )
    )
    state = state_q.scalar_one_or_none()
    if not state:
        raise HTTPException(status_code=400, detail="Abra a questão antes de pedir dica")

    hints_map = {1: qq.hint_1 if hasattr(qq, 'hint_1') else None,
                 2: qq.hint_2 if hasattr(qq, 'hint_2') else None,
                 3: qq.hint_3 if hasattr(qq, 'hint_3') else None}
    next_level = state.hints_used + 1
    if next_level > 3:
        raise HTTPException(status_code=400, detail="Nível máximo de dicas atingido")
    hint_text = hints_map.get(next_level)
    if not hint_text:
        raise HTTPException(status_code=400, detail="Dica não disponível para este nível")

    state.hints_used = next_level
    await event(db, str(attempt.participant_user_id) if attempt.participant_user_id else None, "HINT_USED", {
        "attempt_id": str(attempt.id), "question_id": question_id, "level": next_level
    })
    await db.commit()
    return {"hint": hint_text, "level": next_level}


@router.post("/{attempt_id}/pause-extend", response_model=PauseExtendResponse)
async def pause_extend(
    attempt_id: str,
    payload: PauseExtendRequest,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    """Empurra o prazo da questão pra frente pelo tempo que o aluno ficou
    fora da aba — só se aplica ao tempo POR QUESTÃO/MISTO, que existe pra
    medir tempo de raciocínio numa questão específica. O tempo TOTAL da
    tentativa (modo exame cronometrado) nunca é afetado por isto — continua
    correndo mesmo com o aluno fora, de propósito."""
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    ensure_attempt_active(attempt)

    state_q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt.id,
            AttemptQuestionState.question_id == payload.question_id,
        )
    )
    state = state_q.scalar_one_or_none()
    if state and state.question_deadline_at and payload.away_seconds > 0:
        away = min(payload.away_seconds, 24 * 3600)
        state.question_deadline_at = state.question_deadline_at + timedelta(seconds=away)
        await db.commit()
        await db.refresh(state)

    return PauseExtendResponse(deadline_at=state.question_deadline_at if state else None)


@router.post("/{attempt_id}/submit", response_model=SubmitResponse)
async def submit_attempt(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    if attempt.status not in (AttemptStatus.IN_PROGRESS,):
        raise HTTPException(status_code=400, detail="Tentativa já finalizada")

    # Marca como "sem resposta" (0 pontos) qualquer questão do quiz que o
    # aluno nunca chegou a abrir — acontece quando o tempo TOTAL da
    # tentativa esgota (modo TOTAL/MISTO) antes dele alcançar as últimas
    # questões. Sem isso, essas questões somem sem deixar rastro: contam
    # na nota máxima mas não aparecem em lugar nenhum do histórico.
    answered_q = await db.execute(
        select(Answer.question_id).where(Answer.attempt_id == attempt.id)
    )
    answered_ids = {str(r) for r in answered_q.scalars().all()}
    order_ids = attempt.question_order_json or []
    # A questão pode ter sido apagada/alterada pelo professor depois que a
    # tentativa começou (comum em quiz de teste) — sem essa checagem, tentar
    # criar uma resposta apontando pra um question_id que não existe mais
    # quebra a foreign key e falha a finalização inteira com erro 500.
    existing_qids_q = await db.execute(
        select(QuizQuestion.id).where(QuizQuestion.id.in_(order_ids))
    )
    existing_qids = {str(r) for r in existing_qids_q.scalars().all()}
    for qid in order_ids:
        if qid in answered_ids or qid not in existing_qids:
            continue
        db.add(Answer(
            attempt_id=attempt.id,
            question_id=qid,
            selected_option_id=None,
            text_answer=None,
            is_correct=False,
            points_awarded=0,
            practice_retries=0,
        ))

    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = datetime.now(timezone.utc)
    await audit(db, str(attempt.participant_user_id) if attempt.participant_user_id else None,
                "SUBMIT_ATTEMPT", "Attempt", attempt.id,
                after={"score_obtained": attempt.score_obtained, "score_max": attempt.score_max})
    await db.commit()

    def _is_skipped(a) -> bool:
        return a.selected_option_id is None and not a.text_answer

    correct_count = sum(1 for a in attempt.answers if a.is_correct)
    wrong_count = sum(1 for a in attempt.answers if a.is_correct is False and not _is_skipped(a))
    skipped_count = sum(1 for a in attempt.answers if _is_skipped(a))
    time_spent = None
    if attempt.started_at and attempt.submitted_at:
        # Nunca mostra mais tempo do que o limite TOTAL configurado (quando
        # existe). Sem isso, uma tentativa que ficou parada/travada até ser
        # finalizada bem depois (ex.: reaberta após um erro) mostraria um
        # "Tempo" absurdo, maior que o próprio limite da prova.
        effective_end = attempt.submitted_at
        if attempt.expires_at and attempt.expires_at < effective_end:
            effective_end = attempt.expires_at
        time_spent = int((effective_end - attempt.started_at).total_seconds())

    return SubmitResponse(
        status=attempt.status.value,
        score_obtained=attempt.score_obtained,
        score_max=attempt.score_max,
        correct_count=correct_count,
        wrong_count=wrong_count,
        skipped_count=skipped_count,
        time_spent=time_spent,
    )


@router.get("/me/list", response_model=list[AttemptOut])
async def my_attempts(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    from app.models.quiz import Quiz
    from app.models.assignment import Assignment
    from app.models.classroom import Class

    q = await db.execute(
        select(Attempt).where(Attempt.participant_user_id == me.id)
        .order_by(Attempt.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    attempts = q.scalars().all()

    result = []
    for a in attempts:
        quiz_title = None
        class_id   = None
        class_name = None

        # Fetch quiz title
        quiz_q = await db.execute(select(Quiz).where(Quiz.id == a.quiz_id))
        quiz = quiz_q.scalar_one_or_none()
        if quiz:
            quiz_title = quiz.title

        # Fetch class via assignment
        assignment = None  # ← FIX: initialize before conditional block
        if a.assignment_id:
            assign_q = await db.execute(select(Assignment).where(Assignment.id == a.assignment_id))
            assignment = assign_q.scalar_one_or_none()
            if assignment and assignment.class_id:
                class_id = str(assignment.class_id)
                class_q = await db.execute(select(Class).where(Class.id == assignment.class_id))
                cls = class_q.scalar_one_or_none()
                if cls:
                    class_name = cls.name

        # max_attempts from assignment override or quiz default
        max_attempts = None
        attempts_used = None
        if assignment and quiz:
            max_attempts = assignment.max_attempts or quiz.max_attempts or 1
            # count finished attempts for this quiz by this user
            used_q = await db.execute(
                select(func.count()).where(
                    Attempt.quiz_id == quiz.id,
                    Attempt.participant_user_id == me.id,
                    Attempt.status.in_(["SUBMITTED", "EXPIRED"]),
                )
            )
            attempts_used = used_q.scalar() or 0
        elif quiz:
            max_attempts = quiz.max_attempts or 1
            used_q = await db.execute(
                select(func.count()).where(
                    Attempt.quiz_id == quiz.id,
                    Attempt.participant_user_id == me.id,
                    Attempt.status.in_(["SUBMITTED", "EXPIRED"]),
                )
            )
            attempts_used = used_q.scalar() or 0

        result.append(AttemptOut(
            id=a.id,
            quiz_id=a.quiz_id,
            status=a.status.value,
            started_at=a.started_at,
            expires_at=a.expires_at,
            score_max=a.score_max,
            score_obtained=a.score_obtained,
            quiz_title=quiz_title,
            class_id=class_id,
            class_name=class_name,
            max_attempts=max_attempts,
            attempts_used=attempts_used,
            submitted_at=a.submitted_at,
        ))
    return result


@router.get("/{attempt_id}", response_model=AttemptOut)
async def get_attempt(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    return AttemptOut(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        status=attempt.status.value,
        started_at=attempt.started_at,
        expires_at=attempt.expires_at,
        score_max=attempt.score_max,
        score_obtained=attempt.score_obtained,
    )
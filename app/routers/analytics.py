from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timezone
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import User, UserRole
from app.models.quiz import Quiz, QuizQuestion, QuizOption
from app.models.attempt import Attempt, AttemptStatus, Answer, AttemptQuestionState
from app.models.assignment import Assignment
from app.models.classroom import Class, ClassEnrollment
from app.models.audit import TutorInteraction

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _check_quiz_ownership(quiz: Quiz, me: User):
    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/quiz/{quiz_id}/summary")
async def quiz_summary(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")
    _check_quiz_ownership(quiz, me)
    # Attempts summary
    att_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Attempt.status == "SUBMITTED").label("submitted"),
            func.avg(Attempt.score_obtained).filter(Attempt.status == "SUBMITTED").label("avg_score"),
            func.max(Attempt.score_obtained).filter(Attempt.status == "SUBMITTED").label("max_score"),
        ).where(Attempt.quiz_id == quiz.id)
    )
    row = att_q.first()
    return {
        "quiz_id": str(quiz.id),
        "title": quiz.title,
        "total_attempts": row.total if row else 0,
        "submitted_attempts": row.submitted if row else 0,
        "avg_score": float(row.avg_score) if row and row.avg_score else 0.0,
        "max_score": row.max_score if row else 0,
        "score_max_possible": sum(q.points for q in quiz.questions),}


@router.get("/quiz/{quiz_id}/students")
async def quiz_students(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")
    _check_quiz_ownership(quiz, me)
    att_q = await db.execute(
        select(Attempt).where(Attempt.quiz_id == quiz.id, Attempt.status == "SUBMITTED")
    )
    attempts = att_q.scalars().all()

    # Tempo ativo (soma de opened_at → answered_at por questão) em vez de
    # submitted_at - started_at — mesmo raciocínio do my_performance: se o
    # aluno deixa a aba aberta e só volta depois, o relógio de parede conta
    # esse intervalo todo como "tempo gasto", dando médias absurdas.
    attempt_ids = [a.id for a in attempts]
    active_duration_by_attempt: dict = {}
    if attempt_ids:
        qs_q = await db.execute(
            select(AttemptQuestionState).where(AttemptQuestionState.attempt_id.in_(attempt_ids))
        )
        states = qs_q.scalars().all()
        ans_q = await db.execute(select(Answer).where(Answer.attempt_id.in_(attempt_ids)))
        answered_at_by_key = {(a.attempt_id, a.question_id): a.answered_at for a in ans_q.scalars().all()}
        for qs in states:
            answered_at = answered_at_by_key.get((qs.attempt_id, qs.question_id))
            if qs.opened_at and answered_at:
                gap = (answered_at - qs.opened_at).total_seconds()
                if gap > 0:
                    active_duration_by_attempt[qs.attempt_id] = active_duration_by_attempt.get(qs.attempt_id, 0) + gap

    result = []
    for a in attempts:
        user = a.participant
        result.append({
            "attempt_id": str(a.id),
            "user_id": str(a.participant_user_id) if a.participant_user_id else None,
            "name": user.name if user else a.participant_name,
            "email": user.email if user else a.participant_email,
            "score_obtained": a.score_obtained,
            "score_max": a.score_max,
            "percent": round((a.score_obtained / a.score_max * 100), 1) if a.score_max else 0,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "active_duration_sec": round(active_duration_by_attempt[a.id]) if active_duration_by_attempt.get(a.id) else None,
        })
    return result


@router.get("/quiz/{quiz_id}/questions")
async def quiz_question_analytics(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")
    _check_quiz_ownership(quiz, me)
    # 1 query com GROUP BY — sem N+1
    submitted_attempts_subq = (
        select(Attempt.id).where(
            Attempt.quiz_id == quiz.id,
            Attempt.status == "SUBMITTED",
        ).scalar_subquery()
    )
    agg_q = await db.execute(
        select(
            Answer.question_id,
            func.count().label("total"),
            func.count().filter(Answer.is_correct == True).label("correct"),
        )
        .where(Answer.attempt_id.in_(submitted_attempts_subq))
        .group_by(Answer.question_id)
    )
    stats = {str(row.question_id): row for row in agg_q.all()}

    result = []
    for qq in sorted(quiz.questions, key=lambda x: x.order):
        row = stats.get(str(qq.id))
        total = row.total if row else 0
        correct = row.correct if row else 0
        result.append({
            "question_id": str(qq.id),
            "order": qq.order,
            "statement": qq.statement[:80],
            "difficulty": qq.difficulty,
            "difficulty_confirmed": qq.difficulty_confirmed,
            "total_answers": total,
            "correct_answers": correct,
            "error_rate": round((total - correct) / total * 100, 1) if total else 0,
        })
    return result


@router.get("/quiz/{quiz_id}/difficulty")
async def quiz_difficulty_analytics(
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")
    _check_quiz_ownership(quiz, me)

    rows = await db.execute(text("""
        SELECT qq.difficulty,
               COUNT(ans.id) AS total,
               COUNT(ans.id) FILTER (WHERE ans.is_correct = true) AS acertos
        FROM answers ans
        JOIN quiz_questions qq ON qq.id = ans.question_id
        JOIN attempts a ON a.id = ans.attempt_id
        WHERE a.quiz_id = :qid AND a.status = 'SUBMITTED'
        GROUP BY qq.difficulty
    """), {"qid": quiz_id})
    return [
        {"difficulty": r.difficulty, "total": r.total, "acertos": r.acertos,
         "taxa_acerto": round(r.acertos / r.total * 100, 1) if r.total else 0}
        for r in rows
    ]


@router.get("/student/{student_id}")
async def student_analytics(
    student_id: str,
    class_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    if me.role == UserRole.ALUNO and str(me.id) != student_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    conditions = [
        Attempt.participant_user_id == student_id,
        Attempt.status == "SUBMITTED",
    ]
    if class_id:
        # class_id não é gravado no Attempt na criação — só assignment_id.
        # A turma da tentativa vem da atribuição (Assignment.class_id).
        assignment_ids_q = await db.execute(
            select(Assignment.id).where(Assignment.class_id == class_id)
        )
        assignment_ids = [row[0] for row in assignment_ids_q.all()]
        conditions.append(Attempt.assignment_id.in_(assignment_ids))

    att_q = await db.execute(select(Attempt).where(*conditions))
    attempts = att_q.scalars().all()

    if not attempts:
        return []

    # 1 query para todos os quizzes — sem N+1
    quiz_ids = list({a.quiz_id for a in attempts})
    qz_q = await db.execute(select(Quiz).where(Quiz.id.in_(quiz_ids)))
    quiz_map = {q.id: q for q in qz_q.scalars().all()}

    # 1 query para contagem do tutor com GROUP BY — sem N+1
    attempt_ids = [a.id for a in attempts]
    tutor_q = await db.execute(
        select(TutorInteraction.attempt_id, func.count().label("c"))
        .where(TutorInteraction.attempt_id.in_(attempt_ids))
        .group_by(TutorInteraction.attempt_id)
    )
    tutor_map = {r.attempt_id: r.c for r in tutor_q.all()}

    result = []
    for a in attempts:
        quiz = quiz_map.get(a.quiz_id)
        result.append({
            "attempt_id": str(a.id),
            "quiz_id": str(a.quiz_id),
            "quiz_title": quiz.title if quiz else None,
            "score_obtained": a.score_obtained,
            "score_max": a.score_max,
            "percent": round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "tutor_interactions": tutor_map.get(a.id, 0),
        })
    return result


@router.get("/class/{class_id}")
async def class_analytics(
    class_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")

    class_q = await db.execute(select(Class).where(Class.id == class_id))
    classroom = class_q.scalar_one_or_none()
    if not classroom:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    if me.role == UserRole.PROFESSOR and classroom.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    enroll_q = await db.execute(
        select(ClassEnrollment).where(ClassEnrollment.class_id == class_id, ClassEnrollment.status == "ACTIVE")
    )
    enrollments = enroll_q.scalars().all()

    students = []
    for e in enrollments:
        if not e.user_id:
            continue
        user = e.user
        att_q = await db.execute(
            select(func.count(), func.avg(Attempt.score_obtained))
            .where(Attempt.participant_user_id == e.user_id, Attempt.status == "SUBMITTED")
        )
        row = att_q.first()
        students.append({
            "user_id": str(e.user_id),
            "name": user.name if user else None,
            "email": user.email if user else None,
            "attempts_submitted": row[0] if row else 0,
            "avg_score": float(row[1]) if row and row[1] else 0.0,
        })
    return {"class_id": class_id, "name": classroom.name, "students": students}


@router.get("/student/me/performance")
async def my_performance(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Full self-analytics for the logged-in student."""
    from app.models.attempt import Attempt as Att, Answer as Ans, AttemptStatus, AttemptQuestionState
    from app.models.quiz import Quiz, QuizQuestion, QuizOption
    from app.models.audit import TutorInteraction
    import statistics

    student_id = me.id

    # ── All SUBMITTED attempts ────────────────────────────────────────
    att_q = await db.execute(
        select(Att).where(
            Att.participant_user_id == student_id,
            Att.status == "SUBMITTED",
        ).order_by(Att.submitted_at.asc())
    )
    attempts = att_q.scalars().all()

    # ── All answers for those attempts ───────────────────────────────
    attempt_ids = [a.id for a in attempts]
    ans_q = await db.execute(
        select(Ans).where(Ans.attempt_id.in_(attempt_ids))
    ) if attempt_ids else None
    all_answers = ans_q.scalars().all() if ans_q else []

    # ── Question map ─────────────────────────────────────────────────
    qids = list({a.question_id for a in all_answers})
    qq_map = {}
    if qids:
        qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id.in_(qids)))
        for q in qq_q.scalars().all():
            qq_map[q.id] = q

    # ── Option map (resposta escolhida / correta) ─────────────────────
    opt_map: dict = {}
    if qids:
        opt_q = await db.execute(select(QuizOption).where(QuizOption.question_id.in_(qids)))
        for o in opt_q.scalars().all():
            opt_map.setdefault(o.question_id, []).append(o)

    # ── Quiz map ─────────────────────────────────────────────────────
    quiz_ids = list({a.quiz_id for a in attempts})
    quiz_map = {}
    if quiz_ids:
        qz_q = await db.execute(select(Quiz).where(Quiz.id.in_(quiz_ids)))
        for q in qz_q.scalars().all():
            quiz_map[q.id] = q

    # ── Hints por tentativa + tempo ATIVO por tentativa ─────────────────
    # "Tempo" não pode ser (submitted_at - started_at): se o aluno responde
    # tudo e só fecha a aba sem finalizar, a tentativa fica pendurada e só
    # é encerrada quando ele volta a abrir o quiz — às vezes horas depois —
    # inflando o tempo "gasto" com tempo em que ele nem estava presente.
    # Em vez disso, somamos quanto tempo cada questão levou de verdade
    # (opened_at → answered_at), que já é registrado por questão.
    hints_by_attempt: dict = {}
    active_duration_by_attempt: dict = {}
    if attempt_ids:
        qs_q = await db.execute(
            select(AttemptQuestionState).where(AttemptQuestionState.attempt_id.in_(attempt_ids))
        )
        states = qs_q.scalars().all()
        answered_at_by_key = {(a.attempt_id, a.question_id): a.answered_at for a in all_answers}
        for qs in states:
            aid = qs.attempt_id
            hints_by_attempt[aid] = hints_by_attempt.get(aid, 0) + qs.hints_used
            answered_at = answered_at_by_key.get((qs.attempt_id, qs.question_id))
            if qs.opened_at and answered_at:
                gap = (answered_at - qs.opened_at).total_seconds()
                if gap > 0:
                    active_duration_by_attempt[aid] = active_duration_by_attempt.get(aid, 0) + gap

    # ── Tutor interactions ────────────────────────────────────────────
    tutor_q = await db.execute(
        select(TutorInteraction).where(TutorInteraction.attempt_id.in_(attempt_ids))
    ) if attempt_ids else None
    tutor_ints = tutor_q.scalars().all() if tutor_q else []

    # ── KPIs ──────────────────────────────────────────────────────────
    total_submitted = len(attempts)
    scores_pct = [
        round(a.score_obtained / a.score_max * 100, 1)
        for a in attempts if a.score_max
    ]
    avg_pct = round(sum(scores_pct) / len(scores_pct), 1) if scores_pct else 0

    durations = []
    for a in attempts:
        d = active_duration_by_attempt.get(a.id)
        if d and 0 < d < 7200:
            durations.append(d)
    avg_duration = round(sum(durations) / len(durations)) if durations else 0

    # ── Evolution (per attempt timeline) ─────────────────────────────
    evolution = [
        {
            "attempt_id": str(a.id),
            "quiz_title": quiz_map.get(a.quiz_id, {}).title if hasattr(quiz_map.get(a.quiz_id, {}), "title") else "Quiz",
            "pct": round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "duration_sec": round(active_duration_by_attempt[a.id]) if active_duration_by_attempt.get(a.id) else None,
            "hints_used": hints_by_attempt.get(a.id, 0),
        }
        for a in attempts
    ]

    # ── By difficulty ────────────────────────────────────────────────
    # "correto de primeira" = is_correct E sem retentativas no modo prática
    def _first_try_correct(ans) -> bool:
        return bool(ans.is_correct) and (getattr(ans, "practice_retries", 0) or 0) == 0

    # Dificuldade empírica para questões nunca classificadas pelo professor.
    # "MEDIA" é só o default do banco (toda questão nasce assim), não um
    # sinal real — só confiamos em FACIL/DIFICIL quando o professor escolheu
    # isso manualmente. Para o resto, calculamos a taxa de erro REAL da
    # questão (entre TODOS os alunos que já a responderam, não só este) e
    # bucketizamos com os mesmos limiares já usados nas Estatísticas do
    # professor. Isso é só para exibição — nunca grava de volta no banco.
    TRUSTED_DIFF = {"FACIL", "EASY", "DIFICIL", "HARD"}
    untrusted_qids = [
        qid for qid in qids
        if not (qq_map.get(qid) and (qq_map[qid].difficulty or "").upper() in TRUSTED_DIFF)
    ]
    global_diff_stats: dict = {}
    if untrusted_qids:
        gdiff_q = await db.execute(
            select(
                Ans.question_id,
                func.count().label("total"),
                func.count().filter(Ans.is_correct == True).label("correct"),
            )
            .where(Ans.question_id.in_(untrusted_qids))
            .group_by(Ans.question_id)
        )
        global_diff_stats = {row.question_id: row for row in gdiff_q.all()}

    def _effective_difficulty(qid) -> str:
        qq = qq_map.get(qid)
        explicit = (qq.difficulty or "").upper() if qq else ""
        if explicit in ("FACIL", "EASY"):
            return "FACIL"
        if explicit in ("DIFICIL", "HARD"):
            return "DIFICIL"
        row = global_diff_stats.get(qid)
        if not row or not row.total:
            return "MEDIA"  # sem dado suficiente ainda pra estimar
        error_rate = (row.total - row.correct) / row.total * 100
        if error_rate > 60:
            return "DIFICIL"
        if error_rate > 40:
            return "MEDIA"
        return "FACIL"

    diff_stats: dict = {}
    for ans in all_answers:
        diff = _effective_difficulty(ans.question_id)
        retries = (getattr(ans, "practice_retries", 0) or 0)
        if diff not in diff_stats:
            diff_stats[diff] = {"total": 0, "correct": 0, "with_retry": 0}
        diff_stats[diff]["total"] += 1
        if _first_try_correct(ans):
            diff_stats[diff]["correct"] += 1
        elif ans.is_correct and retries > 0:
            diff_stats[diff]["with_retry"] += 1

    by_difficulty = [
        {
            "difficulty": d,
            "total": v["total"],
            "correct": v["correct"],
            "with_retry": v["with_retry"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
            "pct_retry": round(v["with_retry"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for d, v in diff_stats.items()
    ]

    # ── By topic ──────────────────────────────────────────────────────
    topic_stats: dict = {}
    for ans in all_answers:
        qq = qq_map.get(ans.question_id)
        topic = (qq.topic if qq else None) or "Sem tópico"
        retries = (getattr(ans, "practice_retries", 0) or 0)
        if topic not in topic_stats:
            topic_stats[topic] = {"total": 0, "correct": 0, "with_retry": 0}
        topic_stats[topic]["total"] += 1
        if _first_try_correct(ans):
            topic_stats[topic]["correct"] += 1
        elif ans.is_correct and retries > 0:
            topic_stats[topic]["with_retry"] += 1

    by_topic = sorted([
        {
            "topic": t,
            "total": v["total"],
            "correct": v["correct"],
            "with_retry": v["with_retry"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
            "pct_retry": round(v["with_retry"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for t, v in topic_stats.items()
    ], key=lambda x: x["pct_correct"])

    # ── By skill ──────────────────────────────────────────────────────
    skill_stats: dict = {}
    for ans in all_answers:
        qq = qq_map.get(ans.question_id)
        skill = (qq.skill if qq else None) or "Sem habilidade"
        retries = (getattr(ans, "practice_retries", 0) or 0)
        if skill not in skill_stats:
            skill_stats[skill] = {"total": 0, "correct": 0, "with_retry": 0}
        skill_stats[skill]["total"] += 1
        if _first_try_correct(ans):
            skill_stats[skill]["correct"] += 1
        elif ans.is_correct and retries > 0:
            skill_stats[skill]["with_retry"] += 1

    by_skill = sorted([
        {
            "skill": s,
            "total": v["total"],
            "correct": v["correct"],
            "with_retry": v["with_retry"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
            "pct_retry": round(v["with_retry"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for s, v in skill_stats.items()
    ], key=lambda x: x["pct_correct"])

    # ── Wrong questions review list ───────────────────────────────────
    # Inclui: respostas erradas + respostas que precisaram de retentativa no modo prática
    wrong_ans = [a for a in all_answers if a.is_correct is False or (getattr(a, "practice_retries", 0) or 0) > 0]
    wrong_count: dict = {}
    for ans in wrong_ans:
        qid = ans.question_id
        retries = (getattr(ans, "practice_retries", 0) or 0)
        # peso: resposta errada = 1, com retentativas = retries (reflete dificuldade real)
        wrong_count[qid] = wrong_count.get(qid, 0) + max(1, retries)

    # Índice: attempt_id → submitted_at para ordenar respostas pela mais recente
    attempt_date = {a.id: a.submitted_at for a in attempts}

    review_list = []
    for qid, count in sorted(wrong_count.items(), key=lambda x: -x[1])[:20]:
        qq = qq_map.get(qid)
        if not qq:
            continue
        opts = sorted(opt_map.get(qid, []), key=lambda o: o.order)
        # Última resposta dada a esta questão (pelo attempt mais recente)
        q_answers = sorted(
            [a for a in all_answers if a.question_id == qid],
            key=lambda a: attempt_date.get(a.attempt_id) or datetime.min,
            reverse=True,
        )
        last_ans = q_answers[0] if q_answers else None
        if last_ans is None:
            last_result = "wrong"
        elif last_ans.is_correct and (getattr(last_ans, "practice_retries", 0) or 0) == 0:
            last_result = "correct_first_try"
        elif last_ans.is_correct:
            last_result = "correct_with_retry"
        else:
            last_result = "wrong"

        review_list.append({
            "question_id": str(qid),
            "statement": qq.statement,
            "topic": qq.topic,
            "skill": qq.skill,
            "difficulty": _effective_difficulty(qid),
            "times_wrong": count,
            "last_result": last_result,
            "has_explanation": bool(qq.explanation),
            "explanation": qq.explanation if qq.explanation else None,
            "options": [{"id": str(o.id), "text": o.text, "is_correct": o.is_correct} for o in opts],
        })

    # ── Per-quiz detail ───────────────────────────────────────────────
    quiz_detail = []
    for a in reversed(attempts):  # newest first
        quiz = quiz_map.get(a.quiz_id)
        my_answers = [x for x in all_answers if x.attempt_id == a.id]
        correct_count = sum(1 for x in my_answers if x.is_correct)
        correct_first = sum(1 for x in my_answers if _first_try_correct(x))
        correct_retry = sum(1 for x in my_answers if x.is_correct and (getattr(x, "practice_retries", 0) or 0) > 0)
        wrong_c = sum(1 for x in my_answers if x.is_correct is False)
        hints_c = hints_by_attempt.get(a.id, 0)
        tutor_c = sum(1 for t in tutor_ints if t.attempt_id == a.id)
        dur = round(active_duration_by_attempt[a.id]) if active_duration_by_attempt.get(a.id) else None
        pct = round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0

        # per-question data
        questions_data = []
        for ans in my_answers:
            qq = qq_map.get(ans.question_id)
            if not qq:
                continue
            opts = sorted(opt_map.get(ans.question_id, []), key=lambda o: o.order)
            selected_text = None
            if ans.selected_option_id:
                sel = next((o for o in opts if o.id == ans.selected_option_id), None)
                selected_text = sel.text if sel else None
            correct_text = next((o.text for o in opts if o.is_correct), None)
            questions_data.append({
                "question_id": str(ans.question_id),
                "statement": qq.statement[:100],
                "topic": qq.topic,
                "skill": qq.skill,
                "difficulty": _effective_difficulty(ans.question_id),
                "is_correct": ans.is_correct,
                "has_explanation": bool(qq.explanation),
                "explanation": qq.explanation if qq.explanation else None,
                "selected_option_text": selected_text or ans.text_answer,
                "correct_option_text": correct_text,
                "practice_retries": getattr(ans, "practice_retries", 0) or 0,
            })

        quiz_detail.append({
            "attempt_id": str(a.id),
            "quiz_id": str(a.quiz_id),
            "quiz_title": quiz.title if quiz else "Quiz",
            "status": "SUBMITTED",
            "pct": pct,
            "score_obtained": a.score_obtained,
            "score_max": a.score_max,
            "correct": correct_count,
            "correct_first_try": correct_first,
            "correct_with_retry": correct_retry,
            "wrong": wrong_c,
            "hints_used": hints_by_attempt.get(a.id, 0),
            "tutor_interactions": tutor_c,
            "duration_sec": dur,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "questions": questions_data,
        })

    # ── Tentativas canceladas (turma mudou o tempo no meio do quiz) ────
    # Não apaga o rastro do aluno — ele vê que chegou a começar/responder
    # algo, só não entra na média/nota, já que não foi concluída de fato.
    cancelled_q = await db.execute(
        select(Att).where(
            Att.participant_user_id == student_id,
            Att.status == "CANCELLED",
        ).order_by(Att.started_at.desc())
    )
    cancelled_attempts = cancelled_q.scalars().all()
    if cancelled_attempts:
        c_ids = [c.id for c in cancelled_attempts]
        c_ans_q = await db.execute(select(Ans).where(Ans.attempt_id.in_(c_ids)))
        c_answers = c_ans_q.scalars().all()
        c_quiz_ids = list({c.quiz_id for c in cancelled_attempts})
        c_quiz_q = await db.execute(select(Quiz).where(Quiz.id.in_(c_quiz_ids)))
        c_quiz_map = {q.id: q for q in c_quiz_q.scalars().all()}
        for c in cancelled_attempts:
            answered_n = sum(1 for x in c_answers if x.attempt_id == c.id)
            cq = c_quiz_map.get(c.quiz_id)
            quiz_detail.append({
                "attempt_id": str(c.id),
                "quiz_id": str(c.quiz_id),
                "quiz_title": cq.title if cq else "Quiz",
                "status": "CANCELLED",
                "pct": None,
                "score_obtained": None,
                "score_max": None,
                "correct": None,
                "correct_first_try": None,
                "correct_with_retry": None,
                "wrong": None,
                "hints_used": 0,
                "tutor_interactions": 0,
                "duration_sec": None,
                "submitted_at": c.started_at.isoformat() if c.started_at else None,
                "answered_count": answered_n,
                "questions": [],
            })

    # ── Tutor summary ─────────────────────────────────────────────────
    tutor_total = len(tutor_ints)
    attempts_with_tutor = len({t.attempt_id for t in tutor_ints})
    # avg pct with vs without tutor
    attempt_tutor_set = {t.attempt_id for t in tutor_ints}
    pct_with    = [e["pct"] for e in evolution if e["attempt_id"] in {str(x) for x in attempt_tutor_set}]
    pct_without = [e["pct"] for e in evolution if e["attempt_id"] not in {str(x) for x in attempt_tutor_set}]
    avg_with    = round(sum(pct_with) / len(pct_with), 1) if pct_with else None
    avg_without = round(sum(pct_without) / len(pct_without), 1) if pct_without else None

    # ── Trend (last 7 days vs previous 7) ────────────────────────────
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    def to_aware(dt):
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    recent  = [e for e in evolution if e["submitted_at"] and (now - to_aware(a.submitted_at if (a := next((x for x in attempts if str(x.id) == e["attempt_id"]), None)) else None)).days <= 7 if a and a.submitted_at]
    # simplified trend just using index
    if len(scores_pct) >= 4:
        half = len(scores_pct) // 2
        first_half_avg = sum(scores_pct[:half]) / half
        second_half_avg = sum(scores_pct[half:]) / (len(scores_pct) - half)
        trend = round(second_half_avg - first_half_avg, 1)
    else:
        trend = None

    return {
        "kpis": {
            "total_submitted": total_submitted,
            "avg_pct": avg_pct,
            "avg_duration_sec": avg_duration,
            "trend": trend,
        },
        "evolution": evolution,
        "by_difficulty": by_difficulty,
        "by_topic": by_topic[:15],
        "by_skill": by_skill[:15],
        "review_list": review_list,
        "quiz_detail": quiz_detail,
        "tutor": {
            "total_interactions": tutor_total,
            "attempts_with_tutor": attempts_with_tutor,
            "avg_pct_with_tutor": avg_with,
            "avg_pct_without_tutor": avg_without,
        },
    }


@router.get("/attempts/{attempt_id}/review")
async def attempt_review(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Detalhe completo de uma tentativa especifica, questao a questao —
    usado pelo professor para revisar como um aluno se saiu em um quiz."""
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")

    att_q = await db.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")

    quiz_q = await db.execute(select(Quiz).where(Quiz.id == attempt.quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if me.role == UserRole.PROFESSOR and quiz.professor_id != me.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    q_q = await db.execute(
        select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.order)
    )
    questions = q_q.scalars().all()
    question_ids = [q.id for q in questions]

    opt_q = await db.execute(
        select(QuizOption).where(QuizOption.question_id.in_(question_ids)).order_by(QuizOption.order)
    ) if question_ids else None
    options_by_q: dict = {}
    for o in (opt_q.scalars().all() if opt_q else []):
        options_by_q.setdefault(o.question_id, []).append(o)

    ans_q = await db.execute(select(Answer).where(Answer.attempt_id == attempt.id))
    answers_by_q = {a.question_id: a for a in ans_q.scalars().all()}

    # Tempo ativo (soma de opened_at → answered_at por questão) em vez de
    # submitted_at - started_at — mesmo raciocínio do my_performance: se o
    # aluno deixou a tentativa pendurada e só voltou muito depois, o tempo
    # total decorrido não reflete o tempo que ele realmente gastou.
    states_q = await db.execute(
        select(AttemptQuestionState).where(AttemptQuestionState.attempt_id == attempt.id)
    )
    active_seconds = 0.0
    for qs in states_q.scalars().all():
        ans = answers_by_q.get(qs.question_id)
        if qs.opened_at and ans and ans.answered_at:
            gap = (ans.answered_at - qs.opened_at).total_seconds()
            if gap > 0:
                active_seconds += gap

    questions_out = []
    for q in questions:
        ans = answers_by_q.get(q.id)
        opts = [
            {"id": str(o.id), "text": o.text, "is_correct": o.is_correct}
            for o in options_by_q.get(q.id, [])
        ]
        questions_out.append({
            "question_id": str(q.id),
            "order": q.order,
            "statement": q.statement,
            "difficulty": q.difficulty,
            "options": opts,
            "selected_option_id": str(ans.selected_option_id) if ans and ans.selected_option_id else None,
            "text_answer": ans.text_answer if ans else None,
            "is_correct": ans.is_correct if ans else None,
            "points_awarded": ans.points_awarded if ans else 0,
            "answered": ans is not None,
        })

    duration_sec = round(active_seconds) if active_seconds > 0 else None

    participant = attempt.participant
    return {
        "attempt_id": str(attempt.id),
        "quiz_id": str(quiz.id),
        "quiz_title": quiz.title,
        "student_name": participant.name if participant else attempt.participant_name,
        "student_email": participant.email if participant else attempt.participant_email,
        "status": attempt.status.value if hasattr(attempt.status, "value") else attempt.status,
        "score_obtained": attempt.score_obtained,
        "score_max": attempt.score_max,
        "percent": round(attempt.score_obtained / attempt.score_max * 100, 1) if attempt.score_max else 0,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "duration_sec": duration_sec,
        "questions": questions_out,
    }
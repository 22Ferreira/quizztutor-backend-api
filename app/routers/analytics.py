from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import User, UserRole
from app.models.quiz import Quiz, QuizQuestion
from app.models.attempt import Attempt, AttemptStatus, Answer
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
    result = []
    for qq in sorted(quiz.questions, key=lambda x: x.order):
        ans_q = await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(Answer.is_correct == True).label("correct"),
            ).where(
                Answer.question_id == qq.id,
                Answer.attempt_id.in_(
                    select(Attempt.id).where(Attempt.quiz_id == quiz.id, Attempt.status == "SUBMITTED") )))
        row = ans_q.first()
        total = row.total if row else 0
        correct = row.correct if row else 0
        result.append({
            "question_id": str(qq.id),
            "order": qq.order,
            "statement": qq.statement[:80],
            "difficulty": qq.difficulty,
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
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),):
    if me.role == UserRole.ALUNO and str(me.id) != student_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    att_q = await db.execute(
        select(Attempt).where(
            Attempt.participant_user_id == student_id,
            Attempt.status == "SUBMITTED",
        )
    )
    attempts = att_q.scalars().all()

    result = []
    for a in attempts:
        quiz_q = await db.execute(select(Quiz).where(Quiz.id == a.quiz_id))
        quiz = quiz_q.scalar_one_or_none()
        tutor_q = await db.execute(
            select(func.count()).where(TutorInteraction.attempt_id == a.id)
        )
        tutor_count = tutor_q.scalar() or 0
        result.append({
            "attempt_id": str(a.id),
            "quiz_id": str(a.quiz_id),
            "quiz_title": quiz.title if quiz else None,
            "score_obtained": a.score_obtained,
            "score_max": a.score_max,
            "percent": round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "tutor_interactions": tutor_count,
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

    # ── Quiz map ─────────────────────────────────────────────────────
    quiz_ids = list({a.quiz_id for a in attempts})
    quiz_map = {}
    if quiz_ids:
        qz_q = await db.execute(select(Quiz).where(Quiz.id.in_(quiz_ids)))
        for q in qz_q.scalars().all():
            quiz_map[q.id] = q

    # ── Hints per attempt (sum of AttemptQuestionState.hints_used) ──
    hints_by_attempt: dict = {}
    if attempt_ids:
        qs_q = await db.execute(
            select(AttemptQuestionState).where(AttemptQuestionState.attempt_id.in_(attempt_ids))
        )
        for qs in qs_q.scalars().all():
            aid = qs.attempt_id
            hints_by_attempt[aid] = hints_by_attempt.get(aid, 0) + qs.hints_used

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
        if a.started_at and a.submitted_at:
            d = (a.submitted_at - a.started_at).total_seconds()
            if 0 < d < 7200:
                durations.append(d)
    avg_duration = round(sum(durations) / len(durations)) if durations else 0

    # ── Evolution (per attempt timeline) ─────────────────────────────
    evolution = [
        {
            "attempt_id": str(a.id),
            "quiz_title": quiz_map.get(a.quiz_id, {}).title if hasattr(quiz_map.get(a.quiz_id, {}), "title") else "Quiz",
            "pct": round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "duration_sec": round((a.submitted_at - a.started_at).total_seconds()) if a.started_at and a.submitted_at else None,
            "hints_used": hints_by_attempt.get(a.id, 0),
        }
        for a in attempts
    ]

    # ── By difficulty ────────────────────────────────────────────────
    diff_stats: dict = {}
    for ans in all_answers:
        qq = qq_map.get(ans.question_id)
        diff = (qq.difficulty if qq else None) or "UNKNOWN"
        if diff not in diff_stats:
            diff_stats[diff] = {"total": 0, "correct": 0}
        diff_stats[diff]["total"] += 1
        if ans.is_correct:
            diff_stats[diff]["correct"] += 1

    by_difficulty = [
        {
            "difficulty": d,
            "total": v["total"],
            "correct": v["correct"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for d, v in diff_stats.items()
    ]

    # ── By topic ──────────────────────────────────────────────────────
    topic_stats: dict = {}
    for ans in all_answers:
        qq = qq_map.get(ans.question_id)
        topic = (qq.topic if qq else None) or "Sem tópico"
        if topic not in topic_stats:
            topic_stats[topic] = {"total": 0, "correct": 0}
        topic_stats[topic]["total"] += 1
        if ans.is_correct:
            topic_stats[topic]["correct"] += 1

    by_topic = sorted([
        {
            "topic": t,
            "total": v["total"],
            "correct": v["correct"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for t, v in topic_stats.items()
    ], key=lambda x: x["pct_correct"])

    # ── By skill ──────────────────────────────────────────────────────
    skill_stats: dict = {}
    for ans in all_answers:
        qq = qq_map.get(ans.question_id)
        skill = (qq.skill if qq else None) or "Sem habilidade"
        if skill not in skill_stats:
            skill_stats[skill] = {"total": 0, "correct": 0}
        skill_stats[skill]["total"] += 1
        if ans.is_correct:
            skill_stats[skill]["correct"] += 1

    by_skill = sorted([
        {
            "skill": s,
            "total": v["total"],
            "correct": v["correct"],
            "pct_correct": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
        }
        for s, v in skill_stats.items()
    ], key=lambda x: x["pct_correct"])

    # ── Wrong questions review list ───────────────────────────────────
    wrong_ans = [a for a in all_answers if a.is_correct is False]
    # count per question_id
    wrong_count: dict = {}
    for ans in wrong_ans:
        qid = ans.question_id
        wrong_count[qid] = wrong_count.get(qid, 0) + 1

    review_list = []
    for qid, count in sorted(wrong_count.items(), key=lambda x: -x[1])[:20]:
        qq = qq_map.get(qid)
        if not qq:
            continue
        review_list.append({
            "question_id": str(qid),
            "statement": qq.statement[:120],
            "topic": qq.topic,
            "skill": qq.skill,
            "difficulty": qq.difficulty,
            "times_wrong": count,
            "has_explanation": bool(qq.explanation),
        })

    # ── Per-quiz detail ───────────────────────────────────────────────
    quiz_detail = []
    for a in reversed(attempts):  # newest first
        quiz = quiz_map.get(a.quiz_id)
        my_answers = [x for x in all_answers if x.attempt_id == a.id]
        correct_count = sum(1 for x in my_answers if x.is_correct)
        wrong_c = sum(1 for x in my_answers if x.is_correct is False)
        hints_c = hints_by_attempt.get(a.id, 0)
        tutor_c = sum(1 for t in tutor_ints if t.attempt_id == a.id)
        dur = round((a.submitted_at - a.started_at).total_seconds()) if a.started_at and a.submitted_at else None
        pct = round(a.score_obtained / a.score_max * 100, 1) if a.score_max else 0

        # per-question data
        questions_data = []
        for ans in my_answers:
            qq = qq_map.get(ans.question_id)
            if not qq:
                continue
            questions_data.append({
                "question_id": str(ans.question_id),
                "statement": qq.statement[:100],
                "topic": qq.topic,
                "skill": qq.skill,
                "difficulty": qq.difficulty,
                "is_correct": ans.is_correct,
                "has_explanation": bool(qq.explanation),
                "explanation": qq.explanation if qq.explanation else None,
            })

        quiz_detail.append({
            "attempt_id": str(a.id),
            "quiz_id": str(a.quiz_id),
            "quiz_title": quiz.title if quiz else "Quiz",
            "pct": pct,
            "score_obtained": a.score_obtained,
            "score_max": a.score_max,
            "correct": correct_count,
            "wrong": wrong_c,
            "hints_used": hints_by_attempt.get(a.id, 0),
            "tutor_interactions": tutor_c,
            "duration_sec": dur,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "questions": questions_data,
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
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    def to_aware(dt):
        if dt and dt.tzinfo is None:
            from datetime import timezone as tz
            return dt.replace(tzinfo=tz.utc)
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
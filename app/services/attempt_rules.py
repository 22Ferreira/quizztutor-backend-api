from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.models.quiz import Quiz
from app.models.attempt import Attempt, AttemptStatus
from app.services.quiz_rules import resolve_question_time

def ensure_attempt_active(attempt: Attempt):
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Tentativa não está em andamento")
    if attempt.expires_at and datetime.now(timezone.utc) >= attempt.expires_at:
        attempt.status = AttemptStatus.EXPIRED
        raise HTTPException(status_code=400, detail="Tentativa expirada")

def calc_attempt_expiry(quiz: Quiz) -> datetime | None:
    if quiz.tempo_mode in ("TOTAL","MIXED") and quiz.time_total_seconds:
        return datetime.now(timezone.utc) + timedelta(seconds=int(quiz.time_total_seconds))
    return None

def calc_question_deadline(quiz: Quiz, question) -> datetime | None:
    if quiz.tempo_mode in ("PER_QUESTION","MIXED"):
        sec = resolve_question_time(quiz, question)
        return datetime.now(timezone.utc) + timedelta(seconds=int(sec))
    return None

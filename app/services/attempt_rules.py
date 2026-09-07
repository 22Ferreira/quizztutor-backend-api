from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.models.quiz import Quiz
from app.models.attempt import Attempt, AttemptStatus
from app.services.quiz_rules import effective_time_config

def ensure_attempt_active(attempt: Attempt):
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Tentativa não está em andamento")
    if attempt.expires_at and datetime.now(timezone.utc) >= attempt.expires_at:
        attempt.status = AttemptStatus.EXPIRED
        raise HTTPException(status_code=400, detail="Tentativa expirada")

def calc_attempt_expiry(quiz: Quiz, assignment=None) -> datetime | None:
    mode, total_seconds, _, _ = effective_time_config(quiz, assignment)
    if mode in ("TOTAL", "MIXED") and total_seconds:
        return datetime.now(timezone.utc) + timedelta(seconds=int(total_seconds))
    return None

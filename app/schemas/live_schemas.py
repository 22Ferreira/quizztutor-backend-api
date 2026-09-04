"""
Schemas Pydantic para o módulo Live Session
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ── Criação de sessão ──────────────────────────────────────────────────────────

class LiveSessionCreate(BaseModel):
    quiz_id: uuid.UUID
    classroom_id: Optional[uuid.UUID] = None
    entry_policy: str = "ONLY_CLASSROOM"
    allow_late_join: bool = True
    allow_rejoin: bool = True
    single_approval: bool = True
    shuffle_questions: bool = False
    shuffle_options: bool = False
    show_ranking_students: bool = False
    show_answer_immediate: bool = False
    disable_hints: bool = True
    disable_chat: bool = True
    time_mode: str = "NONE"
    total_time_seconds: Optional[int] = None
    per_question_seconds: Optional[int] = None
    time_by_difficulty: Optional[dict] = None
    scoring_mode: str = "ACCURACY_FIRST"
    max_participants: Optional[int] = None


class LiveSessionOut(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    classroom_id: Optional[uuid.UUID]
    status: str
    session_code: str
    entry_policy: str
    allow_late_join: bool
    allow_rejoin: bool
    shuffle_questions: bool
    shuffle_options: bool
    show_ranking_students: bool
    show_answer_immediate: bool
    disable_hints: bool
    disable_chat: bool
    time_mode: str
    total_time_seconds: Optional[int]
    per_question_seconds: Optional[int]
    time_by_difficulty: Optional[dict]
    scoring_mode: str
    max_participants: Optional[int]
    created_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    quiz_title: Optional[str] = None

    class Config:
        from_attributes = True


# ── Participante ───────────────────────────────────────────────────────────────

class ParticipantOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    status: str
    approved: bool
    joined_at: datetime
    last_seen_at: datetime
    disconnect_count: int

    class Config:
        from_attributes = True


# ── Tentativa / Questão ────────────────────────────────────────────────────────

class LiveQuestionOut(BaseModel):
    """Questão enviada ao aluno durante a sessão ao vivo."""
    question_index: int
    total_questions: int
    question_id: uuid.UUID
    statement: str
    options: List[dict]          # [{id, text}] — sem indicar qual é correta
    time_remaining_seconds: Optional[int]
    session_time_remaining_seconds: Optional[int]


class LiveAnswerIn(BaseModel):
    question_id: uuid.UUID
    selected_option_id: uuid.UUID


class LiveAnswerOut(BaseModel):
    is_correct: bool
    correct_option_id: Optional[uuid.UUID]
    response_time_ms: int
    your_rank: Optional[int]
    message: str


# ── Scoreboard / Ranking ───────────────────────────────────────────────────────

class ScoreboardEntry(BaseModel):
    rank: int
    user_id: uuid.UUID
    user_name: str
    correct_count: int
    answered_count: int
    accuracy: float
    total_time_ms: int
    avg_time_ms: float
    current_question_number: int
    total_questions: int
    status: str
    last_result: Optional[str]   # "correct" | "wrong" | "timeout"

class ScoreboardOut(BaseModel):
    entries: List[ScoreboardEntry]
    updated_at: datetime


# ── Dashboard do professor ─────────────────────────────────────────────────────

class SessionSummaryOut(BaseModel):
    session_id: uuid.UUID
    status: str
    total_participants: int
    online_count: int
    offline_count: int
    finished_count: int
    avg_accuracy: float
    avg_progress: float          # média(respondidas/total)
    avg_time_per_question_ms: float
    time_remaining_seconds: Optional[int]
    scoreboard: ScoreboardOut

class QuestionUserEntry(BaseModel):
    user_id: str
    name: str
    timeout: bool = False

class QuestionStatsOut(BaseModel):
    question_id: uuid.UUID
    statement_preview: str
    total_answers: int
    correct_count: int
    wrong_count: int
    accuracy_pct: float
    avg_time_ms: float
    most_chosen_option_id: Optional[uuid.UUID]
    question_index: Optional[int] = None
    difficulty: Optional[str] = None
    correct_users: List[QuestionUserEntry] = []
    wrong_users: List[QuestionUserEntry] = []

class ProgressDistributionOut(BaseModel):
    """Quantos alunos estão em cada questão"""
    distribution: List[dict]     # [{question_index, count}]


# ── Ações do professor ─────────────────────────────────────────────────────────

class KickBanIn(BaseModel):
    reason: Optional[str] = None

class ApproveIn(BaseModel):
    user_id: uuid.UUID


# ── Estado completo da sessão (para reconexão do professor) ───────────────────

class SessionStateOut(BaseModel):
    session: LiveSessionOut
    summary: SessionSummaryOut
    participants: List[ParticipantOut]
    question_stats: List[QuestionStatsOut]


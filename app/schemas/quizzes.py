from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.models.quiz import QuizStatus, QuizMode, TempoMode, TutorScope, ExplainPolicy


class OptionIn(BaseModel):
    order: int = 0
    text: str
    is_correct: bool = False
    justification: Optional[str] = None


class QuestionIn(BaseModel):
    id: Optional[UUID] = None  # presente ao editar questão existente, None para nova questão
    order: int = 0
    type: str = "MCQ"
    statement: str
    explanation: Optional[str] = None
    difficulty: str = "MEDIA"
    points: int = 1
    time_override_seconds: Optional[int] = None
    hint_1: Optional[str] = None
    hint_2: Optional[str] = None
    hint_3: Optional[str] = None
    topic: Optional[str] = None
    skill: Optional[str] = None
    objective: Optional[str] = None
    short_reference: Optional[str] = None
    media_type: Optional[str] = None        # "IMAGE" | "AUDIO" | "VIDEO"
    media_url: Optional[str] = None
    attachment_urls: Optional[list[str]] = Field(default_factory=list)
    options: list[OptionIn] = Field(default_factory=list)


class OptionOut(BaseModel):
    id: UUID
    order: int
    text: str
    is_correct: bool

    class Config:
        from_attributes = True


class QuestionOut(BaseModel):
    id: UUID
    order: int
    type: str
    statement: str
    explanation: Optional[str]
    difficulty: str
    points: int
    time_override_seconds: Optional[int]
    hint_1: Optional[str]
    hint_2: Optional[str]
    hint_3: Optional[str]
    topic: Optional[str]
    skill: Optional[str]
    objective: Optional[str]
    short_reference: Optional[str] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    attachment_urls: Optional[list[str]] = Field(default_factory=list)
    options: list[OptionOut]

    class Config:
        from_attributes = True


class QuizCreate(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: Optional[str] = None
    mode: QuizMode = QuizMode.ESTUDO
    tempo_mode: TempoMode = TempoMode.NONE
    time_total_seconds: Optional[int] = None
    time_default_question_seconds: Optional[int] = None
    time_by_difficulty: Optional[dict] = None
    max_attempts: int = 1
    shuffle_questions: bool = False
    shuffle_options: bool = False
    hint_levels: int = 0
    explanation_policy: ExplainPolicy = ExplainPolicy.AFTER_CORRECT
    tutor_active: bool = False
    chat_active: bool = False
    availability_start: Optional[datetime] = None
    availability_end: Optional[datetime] = None
    show_correct_immediate: bool = True
    solutions_released: bool = True


class QuizOut(BaseModel):
    id: UUID
    professor_id: UUID
    title: str
    description: Optional[str]
    status: QuizStatus
    mode: QuizMode
    show_correct_immediate: bool
    solutions_released: bool
    availability_start: Optional[datetime]
    availability_end: Optional[datetime]
    tempo_mode: TempoMode
    time_total_seconds: Optional[int]
    time_default_question_seconds: Optional[int]
    time_by_difficulty: Optional[dict]
    max_attempts: int
    shuffle_questions: bool
    shuffle_options: bool
    hint_levels: int
    explanation_policy: ExplainPolicy
    tutor_active: bool
    chat_active: bool
    share_code: Optional[str] = None
    questions: list[QuestionOut] = Field(default_factory=list)
    global_status: Optional[str] = None
    global_request_id: Optional[str] = None
    attempt_count: Optional[int] = None

    class Config:
        from_attributes = True


class QuizUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[QuizMode] = None
    availability_start: Optional[datetime] = None
    availability_end: Optional[datetime] = None
    show_correct_immediate: Optional[bool] = None
    solutions_released: Optional[bool] = None
    max_attempts: Optional[int] = None
    tempo_mode: Optional[TempoMode] = None
    time_total_seconds: Optional[int] = None
    time_default_question_seconds: Optional[int] = None
    time_by_difficulty: Optional[dict] = None
    shuffle_questions: Optional[bool] = None
    shuffle_options: Optional[bool] = None
    hint_levels: Optional[int] = None
    explanation_policy: Optional[ExplainPolicy] = None
    tutor_active: Optional[bool] = None
    chat_active: Optional[bool] = None
    questions: Optional[list[QuestionIn]] = None


class AssignmentCreate(BaseModel):
    type: str  # CLASS/EMAIL_LIST/PUBLIC_LINK
    class_id: Optional[UUID] = None
    emails: Optional[list[str]] = None
    expires_at: Optional[datetime] = None
    require_identity: bool = True
    allow_guest: bool = False
    max_attempts: int = 3
    # Optional overrides (null = use quiz defaults)
    tutor_active_override: Optional[bool] = None
    show_correct_immediate_override: Optional[bool] = None
    practice_mode: Optional[bool] = None
    # Override de tempo por turma — "tudo ou nada" (mesmo esquema do patch)
    time_mode_override: Optional[str] = None
    time_total_seconds_override: Optional[int] = None
    time_default_question_seconds_override: Optional[int] = None
    time_by_difficulty_override: Optional[dict] = None


class TutorConfigIn(BaseModel):
    enabled: bool = True
    scope: TutorScope = TutorScope.SOMENTE_QUESTAO_ATUAL
    allow_out_of_scope: bool = False
    allow_explanation: bool = True
    allow_hints: bool = True
    system_prompt: Optional[str] = None
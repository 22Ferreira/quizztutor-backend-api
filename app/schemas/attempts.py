from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class StartAttemptRequest(BaseModel):
    assignment_id: UUID | None = None
    public_token: str | None = None
    invite_email: str | None = None
    guest_name: str | None = None
    guest_email: str | None = None

class AttemptOut(BaseModel):
    id: UUID
    quiz_id: UUID
    status: str
    started_at: datetime | None = None
    expires_at: datetime | None = None
    score_max: int
    score_obtained: int
    quiz_title: str | None = None
    class_id: str | None = None
    class_name: str | None = None
    max_attempts: int | None = None
    attempts_used: int | None = None
    submitted_at: datetime | None = None

class CurrentQuestionOut(BaseModel):
    question_id: UUID
    order_index: int
    statement: str
    type: str
    options: list[dict]
    deadline_at: datetime | None = None
    time_allotted_seconds: int | None = None
    attempt_expires_at: datetime | None = None
    hints_used: int
    total_questions: int | None = None
    quiz_title: str | None = None
    show_correct_immediate: bool = True
    tutor_active: bool = False
    practice_mode: bool = False
    # Mídia da questão
    media_type: str | None = None
    media_url: str | None = None
    attachment_urls: list[str] = Field(default_factory=list)
    short_reference: str | None = None

class AnswerRequest(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    text_answer: str | None = None
    skip: bool = False              # True = ignorar modo prática e salvar mesmo errado
    practice_retries: int = 0       # quantas vezes errou antes desta resposta final

class PauseExtendRequest(BaseModel):
    question_id: UUID
    away_seconds: int

class PauseExtendResponse(BaseModel):
    deadline_at: datetime | None = None

class SubmitResponse(BaseModel):
    status: str
    score_obtained: int
    score_max: int
    correct_count: int
    wrong_count: int
    skipped_count: int = 0
    time_spent: int | None = None
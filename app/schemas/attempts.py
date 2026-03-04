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
    hints_used: int
    total_questions: int | None = None
    quiz_title: str | None = None
    show_correct_immediate: bool = True
    tutor_active: bool = False

class AnswerRequest(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    text_answer: str | None = None

class SubmitResponse(BaseModel):
    status: str
    score_obtained: int
    score_max: int
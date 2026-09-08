from datetime import datetime
from pydantic import BaseModel

class GlobalSubmitOut(BaseModel):
    request_id: str
    status: str

class GlobalStatusOut(BaseModel):
    status: str
    is_active: bool
    review_note: str | None = None
    slug: str | None = None

class GlobalQuizListItem(BaseModel):
    slug: str
    quiz_id: str
    title: str
    description: str | None = None
    professor_id: str
    approved_at: datetime | None = None
    question_count: int = 0

class AdminReviewIn(BaseModel):
    review_note: str | None = None

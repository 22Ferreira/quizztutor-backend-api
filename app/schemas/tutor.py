from pydantic import BaseModel, Field
from uuid import UUID

class TutorAskRequest(BaseModel):
    attempt_id: UUID
    question_id: UUID | None = None
    message: str = Field(min_length=1, max_length=4000)

class TutorAskResponse(BaseModel):
    message: str
    out_of_scope: bool

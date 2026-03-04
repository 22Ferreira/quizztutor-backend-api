from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class ThreadOut(BaseModel):
    id: UUID
    attempt_id: UUID

class MessageOut(BaseModel):
    id: UUID
    thread_id: UUID
    role: str
    content: str
    out_of_scope: bool
    created_at: datetime | None = None
    deleted_at: datetime | None = None

class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

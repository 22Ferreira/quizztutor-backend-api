from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class IdResponse(BaseModel):
    id: UUID

class MsgResponse(BaseModel):
    message: str

class Timestamped(BaseModel):
    created_at: datetime | None = None

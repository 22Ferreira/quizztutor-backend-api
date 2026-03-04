from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from app.models.user import UserRole

class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    active: bool
    must_change_password: bool
    banned_until: datetime | None = None

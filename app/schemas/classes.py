from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional


class ClassCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    discipline: Optional[str] = None


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    discipline: Optional[str] = None
    active: Optional[bool] = None


class ClassOut(BaseModel):
    id: UUID
    name: str
    code_entry: str
    active: bool
    professor_id: UUID
    created_at: Optional[datetime] = None


class JoinClassRequest(BaseModel):
    code_entry: str = Field(min_length=4, max_length=32)


class InviteEmailsRequest(BaseModel):
    emails: list[EmailStr]


class EnrollmentOut(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    invited_email: Optional[str]
    status: str
    joined_at: Optional[datetime]
    name: Optional[str]
    email: Optional[str]

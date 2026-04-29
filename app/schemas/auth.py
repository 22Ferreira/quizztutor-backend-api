from pydantic import BaseModel, EmailStr, Field
from app.models.user import UserRole

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: UserRole
    must_change_password: bool | None = False

    class Config:
        orm_mode = True

class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)

class RefreshRequest(BaseModel):
    refresh_token: str

class RequestPasswordReset(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

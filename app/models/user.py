import enum, uuid
from sqlalchemy import String, Boolean, DateTime, Enum, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    PROFESSOR = "PROFESSOR"
    ALUNO = "ALUNO"

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    banned_until: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))

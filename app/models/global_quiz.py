import enum, uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, Boolean, Enum, text as sa_text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class GlobalQuizRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"

class GlobalQuizRequest(Base):
    __tablename__ = "global_quiz_requests"
    __table_args__ = (
        UniqueConstraint("quiz_id", name="uq_global_quiz_request_quiz"),
        Index("ix_global_quiz_requests_status_active", "status", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[GlobalQuizRequestStatus] = mapped_column(
        Enum(GlobalQuizRequestStatus, name="global_quiz_request_status"),
        nullable=False,
        server_default=sa_text("'PENDING'"),
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_text("true"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa_text("now()"))
    reviewed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=True)
    approved_public_slug: Mapped[str] = mapped_column(String(80), nullable=True, unique=True)
    quiz = relationship("Quiz", lazy="selectin")

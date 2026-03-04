import enum, uuid
from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean, Text, JSON, Enum, text as sa_text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class AttemptOrigin(str, enum.Enum):
    CLASS = "CLASS"
    EMAIL = "EMAIL"
    PUBLIC_LINK = "PUBLIC_LINK"
    GLOBAL = "GLOBAL"

class AttemptStatus(str, enum.Enum):

    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"

class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="RESTRICT"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_assignments.id", ondelete="SET NULL"), nullable=True, index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)
    participant_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    participant_email: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    participant_name: Mapped[str] = mapped_column(String(255), nullable=True)
    participant_role: Mapped[str] = mapped_column(String(30), nullable=True)
    origin: Mapped[AttemptOrigin] = mapped_column(Enum(AttemptOrigin, name="attempt_origin"), nullable=False, server_default=sa_text("'CLASS'"), index=True)
    global_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("global_quiz_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[AttemptStatus] = mapped_column(Enum(AttemptStatus, name="attempt_status"), nullable=False, server_default=sa_text("'IN_PROGRESS'"), index=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    last_activity_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    question_order_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    score_max: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    score_obtained: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    quiz = relationship("Quiz", lazy="selectin")
    participant = relationship("User", lazy="selectin")
    answers = relationship("Answer", back_populates="attempt", cascade="all, delete-orphan", lazy="selectin")
    question_states = relationship("AttemptQuestionState", back_populates="attempt", cascade="all, delete-orphan", lazy="selectin")

Index("ix_attempt_quiz_user_status", Attempt.quiz_id, Attempt.participant_user_id, Attempt.status)

class AttemptQuestionState(Base):
    __tablename__ = "attempt_question_state"
    __table_args__ = (UniqueConstraint("attempt_id","question_id", name="uq_attempt_question"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="RESTRICT"), index=True)
    opened_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    question_deadline_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_text("false"))
    attempt = relationship("Attempt", back_populates="question_states", lazy="selectin")

class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id","question_id", name="uq_answer_attempt_question"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="RESTRICT"), index=True)
    selected_option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_options.id", ondelete="SET NULL"), nullable=True)
    text_answer: Mapped[str] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=True)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    answered_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    attempt = relationship("Attempt", back_populates="answers", lazy="selectin")
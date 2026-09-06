import enum, uuid, secrets
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Enum, text, UniqueConstraint, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class AssignmentType(str, enum.Enum):
    CLASS = "CLASS"
    EMAIL_LIST = "EMAIL_LIST"
    PUBLIC_LINK = "PUBLIC_LINK"

class Assignment(Base):
    __tablename__ = "quiz_assignments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    type: Mapped[AssignmentType] = mapped_column(Enum(AssignmentType, name="assignment_type"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    require_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    allow_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Optional overrides for this specific assignment (null = use quiz defaults)
    tutor_active_override: Mapped[bool] = mapped_column(Boolean, nullable=True)
    show_correct_immediate_override: Mapped[bool] = mapped_column(Boolean, nullable=True)
    # Modo Prática: resposta errada → dica + retry (não conta na nota até acertar ou desistir)
    practice_mode: Mapped[bool] = mapped_column(Boolean, nullable=True)
    # Override de tempo por turma (null em time_mode_override = usa a configuração do quiz)
    time_mode_override: Mapped[str] = mapped_column(String(16), nullable=True)
    time_total_seconds_override: Mapped[int] = mapped_column(Integer, nullable=True)
    time_default_question_seconds_override: Mapped[int] = mapped_column(Integer, nullable=True)
    time_by_difficulty_override: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    quiz = relationship("Quiz", lazy="selectin")
    classroom = relationship("Class", lazy="selectin")
    invites = relationship("QuizInvite", back_populates="assignment", cascade="all, delete-orphan", lazy="selectin")
    public_links = relationship("PublicLink", back_populates="assignment", cascade="all, delete-orphan", lazy="selectin")

class QuizInvite(Base):
    __tablename__ = "quiz_invites"
    __table_args__ = (UniqueConstraint("assignment_id","email", name="uq_invite_assignment_email"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_assignments.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'INVITED'"))
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    assignment = relationship("Assignment", back_populates="invites", lazy="selectin")

def _token():
    return secrets.token_urlsafe(24)

class PublicLink(Base):
    __tablename__ = "public_links"
    __table_args__ = (UniqueConstraint("token", name="uq_public_link_token"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_assignments.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, default=_token)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    allow_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    require_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    assignment = relationship("Assignment", back_populates="public_links", lazy="selectin")
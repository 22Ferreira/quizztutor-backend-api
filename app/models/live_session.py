"""
live_session.py — Modelos do módulo Sala Ao Vivo
"""
import enum, uuid, random
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Integer, Text, DateTime, ForeignKey,
    Enum, JSON, UniqueConstraint, Index, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class LiveSessionStatus(str, enum.Enum):
    LOBBY   = "LOBBY"
    RUNNING = "RUNNING"
    ENDED   = "ENDED"

class LiveEntryPolicy(str, enum.Enum):
    ONLY_CLASSROOM    = "ONLY_CLASSROOM"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    OPEN_WITH_CODE    = "OPEN_WITH_CODE"

class LiveTimeMode(str, enum.Enum):
    NONE         = "NONE"
    TOTAL        = "TOTAL"
    PER_QUESTION = "PER_QUESTION"
    MIXED        = "MIXED"

class LiveScoringMode(str, enum.Enum):
    ACCURACY_FIRST      = "ACCURACY_FIRST"
    SPEED_AND_ACCURACY  = "SPEED_AND_ACCURACY"

class LiveParticipantStatus(str, enum.Enum):
    WAITING      = "WAITING"
    RUNNING      = "RUNNING"
    DISCONNECTED = "DISCONNECTED"
    PAUSED       = "PAUSED"
    FINISHED     = "FINISHED"
    KICKED       = "KICKED"
    BANNED       = "BANNED"

class LiveAnswerReason(str, enum.Enum):
    NORMAL             = "NORMAL"
    TIMEOUT            = "TIMEOUT"
    DISCONNECT_TIMEOUT = "DISCONNECT_TIMEOUT"


# ── LiveSession ────────────────────────────────────────────────────────────────

class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="RESTRICT"), nullable=False, index=True)
    classroom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    status: Mapped[LiveSessionStatus] = mapped_column(
        Enum(LiveSessionStatus, name="live_session_status"),
        nullable=False, server_default=text("'LOBBY'"), index=True
    )

    session_code: Mapped[str] = mapped_column(String(6), nullable=False, unique=True, index=True)

    # Configurações da sessão
    entry_policy: Mapped[LiveEntryPolicy] = mapped_column(
        Enum(LiveEntryPolicy, name="live_entry_policy"),
        nullable=False, server_default=text("'ONLY_CLASSROOM'")
    )
    allow_late_join: Mapped[bool]       = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    allow_rejoin: Mapped[bool]          = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    shuffle_questions: Mapped[bool]     = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    shuffle_options: Mapped[bool]       = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    show_ranking_students: Mapped[bool]   = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    show_answer_immediate: Mapped[bool]   = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    disable_hints: Mapped[bool]           = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    disable_chat: Mapped[bool]            = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    time_mode: Mapped[LiveTimeMode] = mapped_column(
        Enum(LiveTimeMode, name="live_time_mode"),
        nullable=False, server_default=text("'NONE'")
    )
    total_time_seconds: Mapped[int]        = mapped_column(Integer, nullable=True)
    per_question_seconds: Mapped[int]      = mapped_column(Integer, nullable=True)
    time_by_difficulty: Mapped[dict]       = mapped_column(JSON, nullable=True)

    scoring_mode: Mapped[LiveScoringMode] = mapped_column(
        Enum(LiveScoringMode, name="live_scoring_mode"),
        nullable=False, server_default=text("'ACCURACY_FIRST'")
    )
    max_participants: Mapped[int] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    started_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    quiz        = relationship("Quiz",  lazy="selectin")
    classroom   = relationship("Class", lazy="selectin")
    professor   = relationship("User",  lazy="selectin")
    participants = relationship("LiveParticipant", back_populates="session", cascade="all, delete-orphan", lazy="dynamic")


Index("ix_live_sessions_classroom_status", LiveSession.classroom_id, LiveSession.status)


# ── LiveParticipant ────────────────────────────────────────────────────────────

class LiveParticipant(Base):
    __tablename__ = "live_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_part_session_user"),
    )

    id: Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("live_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    status: Mapped[LiveParticipantStatus] = mapped_column(
        Enum(LiveParticipantStatus, name="live_participant_status"),
        nullable=False, server_default=text("'WAITING'"), index=True
    )
    approved: Mapped[bool]       = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    joined_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    disconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    kicked_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=True)
    banned_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    session = relationship("LiveSession", back_populates="participants")
    user    = relationship("User", lazy="selectin")
    attempt = relationship("LiveAttempt", back_populates="participant", uselist=False, lazy="selectin")


Index("ix_live_part_session_status", LiveParticipant.session_id, LiveParticipant.status)


# ── LiveAttempt ────────────────────────────────────────────────────────────────

class LiveAttempt(Base):
    __tablename__ = "live_attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_attempt_session_user"),
    )

    id: Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("live_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("live_participants.id", ondelete="CASCADE"), nullable=False)

    shuffle_seed: Mapped[int]            = mapped_column(Integer, nullable=False, default=lambda: random.randint(1, 999999))
    question_order: Mapped[list]         = mapped_column(JSON, nullable=False, default=list)  # lista de question_ids em ordem
    current_question_index: Mapped[int]  = mapped_column(Integer, nullable=False, server_default=text("0"))
    answered_count: Mapped[int]          = mapped_column(Integer, nullable=False, server_default=text("0"))
    correct_count: Mapped[int]           = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_time_ms: Mapped[int]           = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Controle de tempo por questão (para reconexão correta)
    question_started_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=True)
    question_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_waiting_reconnect: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    participant = relationship("LiveParticipant", back_populates="attempt")
    answers     = relationship("LiveAnswer", back_populates="attempt", cascade="all, delete-orphan", lazy="selectin")


# ── LiveAnswer ────────────────────────────────────────────────────────────────

class LiveAnswer(Base):
    __tablename__ = "live_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_live_answer_attempt_question"),
    )

    id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), ForeignKey("live_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="RESTRICT"), nullable=False, index=True)

    selected_option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_options.id", ondelete="SET NULL"), nullable=True)
    is_correct: Mapped[bool]       = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    response_time_ms: Mapped[int]  = mapped_column(Integer, nullable=False, server_default=text("0"))
    answered_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    reason: Mapped[LiveAnswerReason] = mapped_column(
        Enum(LiveAnswerReason, name="live_answer_reason"),
        nullable=False, server_default=text("'NORMAL'")
    )

    # Relationships
    attempt  = relationship("LiveAttempt", back_populates="answers", lazy="selectin")
    question = relationship("QuizQuestion", lazy="selectin")
    option   = relationship("QuizOption", lazy="selectin")


Index("ix_live_answer_attempt", LiveAnswer.attempt_id)

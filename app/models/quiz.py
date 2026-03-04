import uuid
import enum
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Integer, Text, Enum, JSON, text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text as sa_text
from app.db.base import Base


class QuizStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class QuizMode(str, enum.Enum):
    ESTUDO = "ESTUDO"
    DIAGNOSTICO = "DIAGNOSTICO"
    AVALIACAO = "AVALIACAO"


class TempoMode(str, enum.Enum):
    NONE = "NONE"
    TOTAL = "TOTAL"
    PER_QUESTION = "PER_QUESTION"
    MIXED = "MIXED"


class TutorScope(str, enum.Enum):
    SOMENTE_QUESTAO_ATUAL = "SOMENTE_QUESTAO_ATUAL"
    QUESTIONARIO = "QUESTIONARIO"
    TURMA = "TURMA"
    LIVRE = "LIVRE"


class ExplainPolicy(str, enum.Enum):
    AFTER_CORRECT = "AFTER_CORRECT"
    AFTER_N_WRONG = "AFTER_N_WRONG"
    ON_DEMAND = "ON_DEMAND"
    END_ONLY = "END_ONLY"


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    professor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[QuizStatus] = mapped_column(Enum(QuizStatus, name="quiz_status"), nullable=False, server_default=text("'DRAFT'"), index=True)
    mode: Mapped[QuizMode] = mapped_column(Enum(QuizMode, name="quiz_mode"), nullable=False, server_default=text("'ESTUDO'"))
    show_correct_immediate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    solutions_released: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    availability_start: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_end: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    tempo_mode: Mapped[TempoMode] = mapped_column(Enum(TempoMode, name="tempo_mode"), nullable=False, server_default=text("'NONE'"))
    time_total_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    time_default_question_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    time_by_difficulty: Mapped[dict] = mapped_column(JSON, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    shuffle_options: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    hint_levels: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    explanation_policy: Mapped[ExplainPolicy] = mapped_column(Enum(ExplainPolicy, name="explain_policy"), nullable=False, server_default=text("'AFTER_CORRECT'"))
    tutor_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    chat_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))
    # NULL in DRAFT — generated only on PUBLISH
    share_code: Mapped[str] = mapped_column(String(20), nullable=True, unique=True, index=True)
    professor = relationship("User", lazy="selectin")
    questions = relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan", lazy="selectin")
    tutor_config = relationship("TutorConfig", uselist=False, back_populates="quiz", cascade="all, delete-orphan", lazy="selectin")


Index("ix_quizzes_prof_status", Quiz.professor_id, Quiz.status)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'MCQ'"))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'MEDIA'"))
    points: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    time_override_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    hint_1: Mapped[str] = mapped_column(Text, nullable=True)
    hint_2: Mapped[str] = mapped_column(Text, nullable=True)
    hint_3: Mapped[str] = mapped_column(Text, nullable=True)
    topic: Mapped[str] = mapped_column(String(255), nullable=True)
    skill: Mapped[str] = mapped_column(String(255), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=True)
    short_reference: Mapped[str] = mapped_column(Text, nullable=True)

    quiz = relationship("Quiz", back_populates="questions", lazy="selectin")
    options = relationship("QuizOption", back_populates="question", cascade="all, delete-orphan", lazy="selectin")


class QuizOption(Base):
    __tablename__ = "quiz_options"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, server_default=sa_text("false"))
    justification: Mapped[str] = mapped_column(Text, nullable=True)
    question = relationship("QuizQuestion", back_populates="options", lazy="selectin")


class TutorConfig(Base):
    __tablename__ = "tutor_config"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    scope: Mapped[TutorScope] = mapped_column(Enum(TutorScope, name="tutor_scope"), nullable=False, server_default=text("'SOMENTE_QUESTAO_ATUAL'"))
    allow_out_of_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    allow_explanation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    allow_hints: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    quiz = relationship("Quiz", back_populates="tutor_config", lazy="selectin")

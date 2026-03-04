import uuid
from sqlalchemy import DateTime, String, ForeignKey, JSON, Text, text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    before: Mapped[dict] = mapped_column(JSON, nullable=True)
    after: Mapped[dict] = mapped_column(JSON, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

Index("ix_audit_action_entity_time", AuditLog.action, AuditLog.entity, AuditLog.created_at)

class EventLog(Base):
    __tablename__ = "event_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class TutorInteraction(Base):
    __tablename__ = "tutor_interactions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=True)
    tutor_message: Mapped[str] = mapped_column(Text, nullable=True)
    out_of_scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'false'"))
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

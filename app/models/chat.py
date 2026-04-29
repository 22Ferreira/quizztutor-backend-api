import uuid
from sqlalchemy import DateTime, ForeignKey, Text, Boolean, String, text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class ChatThread(Base):
    __tablename__ = "chat_threads"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        index=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"))

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True)

    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    out_of_scope: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"))

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"))

    deleted_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=True
)

    deleted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)

    delete_reason: Mapped[str] = mapped_column(Text, nullable=True)
    thread = relationship("ChatThread", lazy="selectin")

    user = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )

    deleted_by_user = relationship(
        "User",
        foreign_keys=[deleted_by],
        lazy="selectin",
    )

# Índice para ordenar mensagens por thread e data
Index("ix_chat_messages_thread_created", ChatMessage.thread_id, ChatMessage.created_at)
import uuid, secrets, hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import DateTime, ForeignKey, String, text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    @staticmethod
    def new(user_id: uuid.UUID, ttl_minutes: int = 30):
        raw = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw)
        expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        return raw, PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires)

Index("ix_pwdreset_user_expires", PasswordResetToken.user_id, PasswordResetToken.expires_at)

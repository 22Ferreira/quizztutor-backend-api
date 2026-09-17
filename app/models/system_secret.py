import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SystemSecret(Base):
    """
    Chaves de API de provedores de IA (Groq, Gemini, ...), configuráveis
    pelo admin em vez de precisar editar o .env do servidor.

    O valor NUNCA é guardado em texto puro — fica cifrado com Fernet
    (chave mestra só existe no .env do servidor, nunca no banco). Sem
    a chave mestra, um dump do banco sozinho não expõe nenhuma chave.
    """
    __tablename__ = "system_secrets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()"))

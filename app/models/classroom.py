import uuid
from sqlalchemy import String, DateTime, Boolean, ForeignKey, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Class(Base):
    __tablename__ = "classes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    professor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str] = mapped_column(String(255), nullable=True)
    code_entry: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    professor = relationship("User", lazy="selectin")
    enrollments = relationship("ClassEnrollment", back_populates="classroom", cascade="all, delete-orphan", lazy="dynamic")


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (
        UniqueConstraint("class_id", "user_id", name="uq_enroll_class_user"),
        UniqueConstraint("class_id", "invited_email", name="uq_enroll_class_email"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    invited_email: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'INVITED'"))
    invited_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Class", back_populates="enrollments", lazy="selectin")
    user = relationship("User", lazy="selectin")

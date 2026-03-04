"""global quiz requests and attempt origin

Revision ID: 20260228_global_quiz_requests
Revises: 
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text, inspect
from sqlalchemy.dialects import postgresql

revision = "20260228_global_quiz_requests"
down_revision = "0000_initial_schema"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = :t AND table_schema = 'public'"
    ), {"t": table})
    return result.scalar() > 0


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c AND table_schema = 'public'"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def _type_exists(type_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM pg_type WHERE typname = :t"
    ), {"t": type_name})
    return result.scalar() > 0


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM pg_indexes WHERE indexname = :i"
    ), {"i": index_name})
    return result.scalar() > 0


def upgrade():
    # Enums - só cria se não existir
    if not _type_exists("global_quiz_request_status"):
        op.execute("CREATE TYPE global_quiz_request_status AS ENUM ('PENDING','APPROVED','REJECTED','REVOKED')")
    if not _type_exists("attempt_origin"):
        op.execute("CREATE TYPE attempt_origin AS ENUM ('CLASS','EMAIL','PUBLIC_LINK','GLOBAL')")

    # Tabela global_quiz_requests - só cria se não existir
    if not _table_exists("global_quiz_requests"):
        op.create_table(
            "global_quiz_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.Enum(name="global_quiz_request_status"), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("approved_public_slug", sa.String(length=80), unique=True, nullable=True),
            sa.UniqueConstraint("quiz_id", name="uq_global_quiz_request_quiz"),
        )

    if not _index_exists("ix_global_quiz_requests_status_active"):
        op.create_index("ix_global_quiz_requests_status_active", "global_quiz_requests", ["status", "is_active"])

    # Colunas em attempts - só adiciona se não existirem
    if not _column_exists("attempts", "participant_role"):
        op.add_column("attempts", sa.Column("participant_role", sa.String(length=30), nullable=True))
    if not _column_exists("attempts", "origin"):
        op.add_column("attempts", sa.Column("origin", sa.Enum(name="attempt_origin"), nullable=False, server_default=sa.text("'CLASS'")))
    if not _column_exists("attempts", "global_request_id"):
        op.add_column("attempts", sa.Column("global_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("global_quiz_requests.id", ondelete="SET NULL"), nullable=True))

    if not _index_exists("ix_attempts_origin"):
        op.create_index("ix_attempts_origin", "attempts", ["origin"])
    if not _index_exists("ix_attempts_global_request_id"):
        op.create_index("ix_attempts_global_request_id", "attempts", ["global_request_id"])


def downgrade():
    if _index_exists("ix_attempts_global_request_id"):
        op.drop_index("ix_attempts_global_request_id", table_name="attempts")
    if _index_exists("ix_attempts_origin"):
        op.drop_index("ix_attempts_origin", table_name="attempts")
    if _column_exists("attempts", "global_request_id"):
        op.drop_column("attempts", "global_request_id")
    if _column_exists("attempts", "origin"):
        op.drop_column("attempts", "origin")
    if _column_exists("attempts", "participant_role"):
        op.drop_column("attempts", "participant_role")
    if _index_exists("ix_global_quiz_requests_status_active"):
        op.drop_index("ix_global_quiz_requests_status_active", table_name="global_quiz_requests")
    if _table_exists("global_quiz_requests"):
        op.drop_table("global_quiz_requests")
    if _type_exists("attempt_origin"):
        op.execute("DROP TYPE attempt_origin")
    if _type_exists("global_quiz_request_status"):
        op.execute("DROP TYPE global_quiz_request_status")

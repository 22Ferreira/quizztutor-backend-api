"""Add NONE to tempo_mode enum and make share_code nullable

Revision ID: 20260302_tempo_none_share_nullable
Revises: 20260301_quiz_share_code
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260302_tempo_none_share_nullable"
down_revision = "20260301_quiz_share_code"
branch_labels = None
depends_on = None


def _enum_has(conn, enum_name, value):
    row = conn.execute(sa.text(
        "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
        "WHERE t.typname=:e AND e.enumlabel=:v"
    ), {"e": enum_name, "v": value}).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    if not _enum_has(conn, "tempo_mode", "NONE"):
        op.execute("ALTER TYPE tempo_mode ADD VALUE 'NONE'")
    op.execute("ALTER TABLE quizzes ALTER COLUMN share_code DROP NOT NULL")
    op.execute("UPDATE quizzes SET share_code = NULL WHERE status = 'DRAFT'")
    op.execute(
        "UPDATE quizzes SET tempo_mode = 'NONE' "
        "WHERE tempo_mode = 'TOTAL' AND time_total_seconds IS NULL"
    )


def downgrade():
    op.execute("UPDATE quizzes SET share_code = encode(gen_random_bytes(4),'hex') WHERE share_code IS NULL")
    op.execute("ALTER TABLE quizzes ALTER COLUMN share_code SET NOT NULL")

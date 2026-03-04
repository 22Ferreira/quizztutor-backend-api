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

    # Add NONE to tempo_mode enum
    if not _enum_has(conn, "tempo_mode", "NONE"):
        op.execute("ALTER TYPE tempo_mode ADD VALUE 'NONE'")

    # Make share_code nullable (generated on publish, not on create)
    op.execute("ALTER TABLE quizzes ALTER COLUMN share_code DROP NOT NULL")
    # Clear share_code from DRAFT quizzes
    op.execute("UPDATE quizzes SET share_code = NULL WHERE status = 'DRAFT'")
    # Set default tempo_mode to NONE for existing rows that have no time set
    op.execute(
        "UPDATE quizzes SET tempo_mode = 'NONE' "
        "WHERE tempo_mode = 'TOTAL' AND time_total_seconds IS NULL"
    )


def downgrade():
    op.execute("UPDATE quizzes SET share_code = encode(gen_random_bytes(4),'hex') WHERE share_code IS NULL")
    op.execute("ALTER TABLE quizzes ALTER COLUMN share_code SET NOT NULL")


"""Add tutor/gabarito overrides to quiz_assignments

Revision ID: 20260302_assignment_overrides
Revises: 20260302_tempo_none_share_nullable
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260302_assignment_overrides"
down_revision = "20260302_tempo_none_share_nullable"
branch_labels = None
depends_on = None


def _col_exists(conn, table, col):
    row = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": col}).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    if not _col_exists(conn, "quiz_assignments", "tutor_active_override"):
        op.add_column("quiz_assignments", sa.Column("tutor_active_override", sa.Boolean(), nullable=True))
    if not _col_exists(conn, "quiz_assignments", "show_correct_immediate_override"):
        op.add_column("quiz_assignments", sa.Column("show_correct_immediate_override", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("quiz_assignments", "show_correct_immediate_override")
    op.drop_column("quiz_assignments", "tutor_active_override")
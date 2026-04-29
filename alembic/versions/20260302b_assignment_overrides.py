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

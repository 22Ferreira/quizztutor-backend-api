"""add time override fields to quiz_assignments

Revision ID: 20260906_assignment_time_override
Revises: 20260904_live_session_single_approval
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "20260906_assignment_time_override"
down_revision = "20260904_live_session_single_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("quiz_assignments",
        sa.Column("time_mode_override", sa.String(16), nullable=True))
    op.add_column("quiz_assignments",
        sa.Column("time_total_seconds_override", sa.Integer(), nullable=True))
    op.add_column("quiz_assignments",
        sa.Column("time_default_question_seconds_override", sa.Integer(), nullable=True))
    op.add_column("quiz_assignments",
        sa.Column("time_by_difficulty_override", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("quiz_assignments", "time_by_difficulty_override")
    op.drop_column("quiz_assignments", "time_default_question_seconds_override")
    op.drop_column("quiz_assignments", "time_total_seconds_override")
    op.drop_column("quiz_assignments", "time_mode_override")

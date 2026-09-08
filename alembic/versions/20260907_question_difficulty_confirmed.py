"""add difficulty_confirmed flag to quiz_questions

Revision ID: 20260907_question_difficulty_confirmed
Revises: 20260906_assignment_time_override
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "20260907_question_difficulty_confirmed"
down_revision = "20260906_assignment_time_override"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("quiz_questions",
        sa.Column("difficulty_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("quiz_questions", "difficulty_confirmed")

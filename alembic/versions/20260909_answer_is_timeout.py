"""add is_timeout flag to answers

Revision ID: 20260909_answer_is_timeout
Revises: 20260907_question_difficulty_confirmed
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "20260909_answer_is_timeout"
down_revision = "20260907_question_difficulty_confirmed"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "answers",
        sa.Column("is_timeout", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("answers", "is_timeout")

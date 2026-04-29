"""add media fields to quiz_questions

Revision ID: 20260305_question_media
Revises: 20260304_perf_indexes
Create Date: 2026-03-05

Campos adicionados (todos opcionais — retrocompatível):
  quiz_questions.media_type      TEXT nullable  (IMAGE | AUDIO | VIDEO)
  quiz_questions.media_url       TEXT nullable
  quiz_questions.attachment_urls JSON nullable  (lista de strings)
"""

from alembic import op
import sqlalchemy as sa

revision = "20260305_question_media"
down_revision = "20260304_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quiz_questions",
        sa.Column("media_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "quiz_questions",
        sa.Column("media_url", sa.Text, nullable=True),
    )
    op.add_column(
        "quiz_questions",
        sa.Column("attachment_urls", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quiz_questions", "attachment_urls")
    op.drop_column("quiz_questions", "media_url")
    op.drop_column("quiz_questions", "media_type")

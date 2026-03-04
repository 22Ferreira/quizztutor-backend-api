"""add max_attempts to quiz_assignments

Revision ID: add_max_attempts_assignments
Revises: 20260228_global_quiz_requests
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'add_max_attempts_assignments'
down_revision = '20260228_global_quiz_requests'
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def upgrade() -> None:
    # Idempotente: só adiciona se ainda não existe
    if not _column_exists('quiz_assignments', 'max_attempts'):
        op.add_column(
            'quiz_assignments',
            sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3')
        )


def downgrade() -> None:
    if _column_exists('quiz_assignments', 'max_attempts'):
        op.drop_column('quiz_assignments', 'max_attempts')

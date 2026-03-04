"""add share_code to quizzes

Revision ID: 20260301_quiz_share_code
Revises: add_max_attempts_assignments
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
import random, string

revision = "20260301_quiz_share_code"
down_revision = "add_max_attempts_assignments"
branch_labels = None
depends_on = None


def _gen_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def upgrade():
    op.add_column("quizzes", sa.Column("share_code", sa.String(20), nullable=True, unique=True))

    # Backfill existing quizzes with a unique code
    conn = op.get_bind()
    quizzes = conn.execute(sa.text("SELECT id FROM quizzes WHERE share_code IS NULL")).fetchall()
    used = set()
    for (qid,) in quizzes:
        code = _gen_code()
        while code in used:
            code = _gen_code()
        used.add(code)
        conn.execute(sa.text("UPDATE quizzes SET share_code = :c WHERE id = :id"), {"c": code, "id": str(qid)})

    # Now make it non-nullable
    op.alter_column("quizzes", "share_code", nullable=False)
    op.create_index("ix_quizzes_share_code", "quizzes", ["share_code"], unique=True)


def downgrade():
    op.drop_index("ix_quizzes_share_code", table_name="quizzes")
    op.drop_column("quizzes", "share_code")

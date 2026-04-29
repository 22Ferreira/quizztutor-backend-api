"""add show_answer_immediate, disable_hints, disable_chat to live_sessions

Revision ID: 20260312_live_session_config
Revises: 20260306_live_session
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260312_live_session_config"
down_revision = "20260306_live_session"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("live_sessions",
        sa.Column("show_answer_immediate", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")))
    op.add_column("live_sessions",
        sa.Column("disable_hints", sa.Boolean(), nullable=False,
                  server_default=sa.text("TRUE")))
    op.add_column("live_sessions",
        sa.Column("disable_chat", sa.Boolean(), nullable=False,
                  server_default=sa.text("TRUE")))
    # Corrigir default do show_ranking_students para FALSE (por padrão desativado)
    op.alter_column("live_sessions", "show_ranking_students",
                    server_default=sa.text("FALSE"))


def downgrade():
    op.drop_column("live_sessions", "show_answer_immediate")
    op.drop_column("live_sessions", "disable_hints")
    op.drop_column("live_sessions", "disable_chat")
    op.alter_column("live_sessions", "show_ranking_students",
                    server_default=sa.text("TRUE"))

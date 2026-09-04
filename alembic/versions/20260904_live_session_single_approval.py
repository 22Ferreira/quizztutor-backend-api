"""add single_approval to live_sessions

Revision ID: 20260904_live_session_single_approval
Revises: 20260312_live_session_config
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "20260904_live_session_single_approval"
down_revision = "20260312_live_session_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("live_sessions",
        sa.Column("single_approval", sa.Boolean(), nullable=False,
                  server_default=sa.text("TRUE")))


def downgrade():
    op.drop_column("live_sessions", "single_approval")

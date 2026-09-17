"""add system_secrets table for admin-managed AI provider keys

Revision ID: 20260917_system_secrets
Revises: 20260909_answer_is_timeout
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260917_system_secrets"
down_revision = "20260909_answer_is_timeout"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key_name", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_system_secrets_key_name", "system_secrets", ["key_name"], unique=True)


def downgrade():
    op.drop_index("ix_system_secrets_key_name", table_name="system_secrets")
    op.drop_table("system_secrets")

"""
Migration: Tabelas do módulo Sala Ao Vivo (Live Quiz)
Revises: 20260305_question_media
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '20260306_live_session'
down_revision = '20260305_question_media'
branch_labels = None
depends_on = None


def upgrade():
    # Enums
    op.execute("CREATE TYPE live_session_status AS ENUM ('LOBBY', 'RUNNING', 'ENDED')")
    op.execute("CREATE TYPE live_entry_policy AS ENUM ('ONLY_CLASSROOM', 'APPROVAL_REQUIRED', 'OPEN_WITH_CODE')")
    op.execute("CREATE TYPE live_time_mode AS ENUM ('NONE', 'TOTAL', 'PER_QUESTION', 'MIXED')")
    op.execute("CREATE TYPE live_scoring_mode AS ENUM ('ACCURACY_FIRST', 'SPEED_AND_ACCURACY')")
    op.execute("CREATE TYPE live_participant_status AS ENUM ('WAITING', 'RUNNING', 'DISCONNECTED', 'PAUSED', 'FINISHED', 'KICKED', 'BANNED')")
    op.execute("CREATE TYPE live_answer_reason AS ENUM ('NORMAL', 'TIMEOUT', 'DISCONNECT_TIMEOUT')")

    # live_sessions
    op.create_table(
        'live_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('quiz_id', UUID(as_uuid=True), sa.ForeignKey('quizzes.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('classroom_id', UUID(as_uuid=True), sa.ForeignKey('classes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.Text, nullable=False, server_default='LOBBY'),
        sa.Column('session_code', sa.String(6), nullable=False, unique=True),
        sa.Column('entry_policy', sa.Text, nullable=False, server_default='ONLY_CLASSROOM'),
        sa.Column('allow_late_join', sa.Boolean, nullable=False, server_default='TRUE'),
        sa.Column('allow_rejoin', sa.Boolean, nullable=False, server_default='TRUE'),
        sa.Column('shuffle_questions', sa.Boolean, nullable=False, server_default='FALSE'),
        sa.Column('shuffle_options', sa.Boolean, nullable=False, server_default='FALSE'),
        sa.Column('show_ranking_students', sa.Boolean, nullable=False, server_default='TRUE'),
        sa.Column('time_mode', sa.Text, nullable=False, server_default='NONE'),
        sa.Column('total_time_seconds', sa.Integer, nullable=True),
        sa.Column('per_question_seconds', sa.Integer, nullable=True),
        sa.Column('time_by_difficulty', sa.JSON, nullable=True),
        sa.Column('scoring_mode', sa.Text, nullable=False, server_default='ACCURACY_FIRST'),
        sa.Column('max_participants', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_live_sessions_status', 'live_sessions', ['status'])
    op.create_index('ix_live_sessions_classroom_status', 'live_sessions', ['classroom_id', 'status'])

    # live_participants
    op.create_table(
        'live_participants',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('live_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Text, nullable=False, server_default='WAITING'),
        sa.Column('approved', sa.Boolean, nullable=False, server_default='FALSE'),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('disconnect_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('kicked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('banned_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('session_id', 'user_id', name='uq_live_part_session_user'),
    )
    op.create_index('ix_live_part_session_status', 'live_participants', ['session_id', 'status'])

    # live_attempts
    op.create_table(
        'live_attempts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('live_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('participant_id', UUID(as_uuid=True), sa.ForeignKey('live_participants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shuffle_seed', sa.Integer, nullable=False),
        sa.Column('question_order', sa.JSON, nullable=False),
        sa.Column('current_question_index', sa.Integer, nullable=False, server_default='0'),
        sa.Column('answered_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('correct_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_time_ms', sa.Integer, nullable=False, server_default='0'),
        sa.Column('question_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('question_deadline_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paused_waiting_reconnect', sa.Boolean, nullable=False, server_default='FALSE'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('session_id', 'user_id', name='uq_live_attempt_session_user'),
    )
    op.create_index('ix_live_attempt_session', 'live_attempts', ['session_id'])

    # live_answers
    op.create_table(
        'live_answers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('attempt_id', UUID(as_uuid=True), sa.ForeignKey('live_attempts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_id', UUID(as_uuid=True), sa.ForeignKey('quiz_questions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('selected_option_id', UUID(as_uuid=True), sa.ForeignKey('quiz_options.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_correct', sa.Boolean, nullable=False, server_default='FALSE'),
        sa.Column('response_time_ms', sa.Integer, nullable=False, server_default='0'),
        sa.Column('answered_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('reason', sa.Text, nullable=False, server_default='NORMAL'),
        sa.UniqueConstraint('attempt_id', 'question_id', name='uq_live_answer_attempt_question'),
    )
    op.create_index('ix_live_answer_attempt', 'live_answers', ['attempt_id'])


def downgrade():
    op.drop_table('live_answers')
    op.drop_table('live_attempts')
    op.drop_table('live_participants')
    op.drop_table('live_sessions')
    op.execute("DROP TYPE IF EXISTS live_answer_reason")
    op.execute("DROP TYPE IF EXISTS live_participant_status")
    op.execute("DROP TYPE IF EXISTS live_scoring_mode")
    op.execute("DROP TYPE IF EXISTS live_time_mode")
    op.execute("DROP TYPE IF EXISTS live_entry_policy")
    op.execute("DROP TYPE IF EXISTS live_session_status")

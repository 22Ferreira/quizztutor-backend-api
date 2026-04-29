"""add performance indexes for high concurrency

Revision ID: 20260304_perf_indexes
Revises: 20260302_tempo_none_share_nullable
Create Date: 2026-03-04

Índices adicionados:
- attempts: quiz_id + status + submitted_at  (contagem max_attempts)
- attempts: participant_user_id + status      (my_attempts list)
- answers:  attempt_id + is_correct           (analytics GROUP BY)
- chat_messages: thread_id + created_at       (paginação cursor)
- class_enrollments: class_id + status        (list students)
- quiz_questions: quiz_id + order             (sorted questions)
"""
from alembic import op

revision = "20260304_perf_indexes"
down_revision = "20260302_assignment_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tentativas por quiz + status (usado na contagem de max_attempts)
    op.create_index(
        "ix_attempts_quiz_status_submitted",
        "attempts",
        ["quiz_id", "status", "submitted_at"],
        if_not_exists=True,
    )
    # Tentativas por usuário + status (usado em my_attempts)
    op.create_index(
        "ix_attempts_user_status",
        "attempts",
        ["participant_user_id", "status"],
        if_not_exists=True,
    )
    # Respostas por tentativa + is_correct (analytics GROUP BY)
    op.create_index(
        "ix_answers_attempt_correct",
        "answers",
        ["attempt_id", "is_correct"],
        if_not_exists=True,
    )
    # Mensagens de chat por thread + data (paginação cursor-based)
    op.create_index(
        "ix_chat_messages_thread_created",
        "chat_messages",
        ["thread_id", "created_at"],
        if_not_exists=True,
    )
    # Matrículas por turma + status (list students, enrollments)
    op.create_index(
        "ix_enrollments_class_status",
        "class_enrollments",
        ["class_id", "status"],
        if_not_exists=True,
    )
    # Questões por quiz + order (sorted em todo endpoint de quiz)
    op.create_index(
        "ix_quiz_questions_quiz_order",
        "quiz_questions",
        ["quiz_id", "order"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_attempts_quiz_status_submitted", table_name="attempts", if_exists=True)
    op.drop_index("ix_attempts_user_status", table_name="attempts", if_exists=True)
    op.drop_index("ix_answers_attempt_correct", table_name="answers", if_exists=True)
    op.drop_index("ix_chat_messages_thread_created", table_name="chat_messages", if_exists=True)
    op.drop_index("ix_enrollments_class_status", table_name="class_enrollments", if_exists=True)
    op.drop_index("ix_quiz_questions_quiz_order", table_name="quiz_questions", if_exists=True)

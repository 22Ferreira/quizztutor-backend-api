"""initial schema — creates all tables from scratch

Revision ID: 0000_initial_schema
Revises:
Create Date: 2026-03-01

This is the canonical baseline migration.
Running `alembic upgrade head` on a fresh database will execute this first,
then the incremental migrations in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0000_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── Helper: skip if table/type already exists (safe for re-runs) ──────────
    def table_exists(name):
        return conn.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n)"
        ), {"n": name}).scalar()

    def enum_exists(name):
        return conn.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname=:n)"
        ), {"n": name}).scalar()

    def col_exists(table, col):
        return conn.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c)"
        ), {"t": table, "c": col}).scalar()

    def index_exists(name):
        return conn.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname=:n)"
        ), {"n": name}).scalar()

    # ── ENUMs ──────────────────────────────────────────────────────────────────
    if not enum_exists("user_role"):
        op.execute("CREATE TYPE user_role AS ENUM ('ADMIN','PROFESSOR','ALUNO')")

    if not enum_exists("quiz_status"):
        op.execute("CREATE TYPE quiz_status AS ENUM ('DRAFT','PUBLISHED','CLOSED','ARCHIVED')")

    if not enum_exists("quiz_mode"):
        op.execute("CREATE TYPE quiz_mode AS ENUM ('ESTUDO','DIAGNOSTICO','AVALIACAO')")

    if not enum_exists("tempo_mode"):
        op.execute("CREATE TYPE tempo_mode AS ENUM ('TOTAL','PER_QUESTION','MIXED')")

    if not enum_exists("tutor_scope"):
        op.execute("CREATE TYPE tutor_scope AS ENUM ('SOMENTE_QUESTAO_ATUAL','QUESTIONARIO','TURMA','LIVRE')")

    if not enum_exists("explain_policy"):
        op.execute("CREATE TYPE explain_policy AS ENUM ('AFTER_CORRECT','AFTER_N_WRONG','ON_DEMAND','END_ONLY')")

    if not enum_exists("assignment_type"):
        op.execute("CREATE TYPE assignment_type AS ENUM ('CLASS','EMAIL_LIST','PUBLIC_LINK')")

    if not enum_exists("attempt_status"):
        op.execute("CREATE TYPE attempt_status AS ENUM ('IN_PROGRESS','SUBMITTED','EXPIRED','CANCELLED')")

    if not enum_exists("attempt_origin"):
        op.execute("CREATE TYPE attempt_origin AS ENUM ('CLASS','EMAIL','PUBLIC_LINK','GLOBAL')")

    if not enum_exists("global_quiz_request_status"):
        op.execute("CREATE TYPE global_quiz_request_status AS ENUM ('PENDING','APPROVED','REJECTED','REVOKED')")

    # ── USERS ──────────────────────────────────────────────────────────────────
    if not table_exists("users"):
        op.create_table("users",
            sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("email",               sa.String(255), nullable=False, unique=True),
            sa.Column("name",                sa.String(255), nullable=False),
            sa.Column("password_hash",       sa.String(255), nullable=False),
            sa.Column("role",                sa.Enum(name="user_role"), nullable=False),
            sa.Column("active",              sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("must_change_password",sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("token_version",       sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("banned_until",        sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at",          sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_role",  "users", ["role"])

    # ── CLASSES ────────────────────────────────────────────────────────────────
    if not table_exists("classes"):
        op.create_table("classes",
            sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("professor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name",         sa.String(255), nullable=False),
            sa.Column("discipline",   sa.String(255), nullable=True),
            sa.Column("code_entry",   sa.String(32),  nullable=False, unique=True),
            sa.Column("active",       sa.Boolean(),   nullable=False, server_default=sa.text("true")),
            sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_classes_professor_id", "classes", ["professor_id"])
        op.create_index("ix_classes_code_entry",   "classes", ["code_entry"], unique=True)

    if not table_exists("class_enrollments"):
        op.create_table("class_enrollments",
            sa.Column("id",             postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("class_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id",        postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("invited_email",  sa.String(255), nullable=True),
            sa.Column("status",         sa.String(16),  nullable=False, server_default=sa.text("'INVITED'")),
            sa.Column("invited_at",     sa.DateTime(timezone=True), nullable=True),
            sa.Column("joined_at",      sa.DateTime(timezone=True), nullable=True),
            sa.Column("removed_at",     sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("class_id", "user_id",       name="uq_enroll_class_user"),
            sa.UniqueConstraint("class_id", "invited_email", name="uq_enroll_class_email"),
        )
        op.create_index("ix_class_enrollments_class_id",      "class_enrollments", ["class_id"])
        op.create_index("ix_class_enrollments_user_id",       "class_enrollments", ["user_id"])
        op.create_index("ix_class_enrollments_invited_email", "class_enrollments", ["invited_email"])

    # ── QUIZZES ────────────────────────────────────────────────────────────────
    if not table_exists("quizzes"):
        op.create_table("quizzes",
            sa.Column("id",                         postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("professor_id",               postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("title",                      sa.String(255), nullable=False),
            sa.Column("description",                sa.Text(),      nullable=True),
            sa.Column("status",                     sa.Enum(name="quiz_status"),   nullable=False, server_default=sa.text("'DRAFT'")),
            sa.Column("mode",                       sa.Enum(name="quiz_mode"),     nullable=False, server_default=sa.text("'ESTUDO'")),
            sa.Column("show_correct_immediate",     sa.Boolean(),   nullable=False, server_default=sa.text("TRUE")),
            sa.Column("solutions_released",         sa.Boolean(),   nullable=False, server_default=sa.text("TRUE")),
            sa.Column("availability_start",         sa.DateTime(timezone=True), nullable=True),
            sa.Column("availability_end",           sa.DateTime(timezone=True), nullable=True),
            sa.Column("tempo_mode",                 sa.Enum(name="tempo_mode"),    nullable=False, server_default=sa.text("'TOTAL'")),
            sa.Column("time_total_seconds",         sa.Integer(),   nullable=True),
            sa.Column("time_default_question_seconds", sa.Integer(), nullable=True),
            sa.Column("time_by_difficulty",         sa.JSON(),      nullable=True),
            sa.Column("max_attempts",               sa.Integer(),   nullable=False, server_default=sa.text("1")),
            sa.Column("shuffle_questions",          sa.Boolean(),   nullable=False, server_default=sa.text("FALSE")),
            sa.Column("shuffle_options",            sa.Boolean(),   nullable=False, server_default=sa.text("FALSE")),
            sa.Column("hint_levels",                sa.Integer(),   nullable=False, server_default=sa.text("0")),
            sa.Column("explanation_policy",         sa.Enum(name="explain_policy"), nullable=False, server_default=sa.text("'AFTER_CORRECT'")),
            sa.Column("tutor_active",               sa.Boolean(),   nullable=False, server_default=sa.text("FALSE")),
            sa.Column("chat_active",                sa.Boolean(),   nullable=False, server_default=sa.text("FALSE")),
            sa.Column("share_code",                 sa.String(20),  nullable=True,  unique=True),
            sa.Column("created_at",                 sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at",                 sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_quizzes_professor_id",   "quizzes", ["professor_id"])
        op.create_index("ix_quizzes_status",         "quizzes", ["status"])
        op.create_index("ix_quizzes_share_code",     "quizzes", ["share_code"], unique=True)
        op.create_index("ix_quizzes_prof_status",    "quizzes", ["professor_id", "status"])

    if not table_exists("quiz_questions"):
        op.create_table("quiz_questions",
            sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("statement",        sa.Text(),     nullable=False),
            sa.Column("type",             sa.String(32), nullable=False, server_default=sa.text("'MULTIPLE_CHOICE'")),
            sa.Column("difficulty",       sa.String(16), nullable=False, server_default=sa.text("'MEDIA'")),
            sa.Column("explanation",      sa.Text(),     nullable=True),
            sa.Column("hint_1",           sa.Text(),     nullable=True),
            sa.Column("hint_2",           sa.Text(),     nullable=True),
            sa.Column("hint_3",           sa.Text(),     nullable=True),
            sa.Column("objective",        sa.Text(),     nullable=True),
            sa.Column("time_override_sec",sa.Integer(),  nullable=True),
            sa.Column("order_index",      sa.Integer(),  nullable=False, server_default=sa.text("0")),
            sa.Column("points",           sa.Integer(),  nullable=False, server_default=sa.text("1")),
        )
        op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])

    if not table_exists("quiz_options"):
        op.create_table("quiz_options",
            sa.Column("id",         postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("question_id",postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("text",       sa.Text(),    nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
            sa.Column("order",      sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_quiz_options_question_id", "quiz_options", ["question_id"])

    if not table_exists("tutor_config"):
        op.create_table("tutor_config",
            sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("scope",            sa.Enum(name="tutor_scope"), nullable=False, server_default=sa.text("'SOMENTE_QUESTAO_ATUAL'")),
            sa.Column("instructions",     sa.Text(), nullable=True),
            sa.Column("enabled",          sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("allow_out_of_scope",sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
            sa.Column("allow_explanation",sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("allow_hints",      sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        )

    # ── ASSIGNMENTS ────────────────────────────────────────────────────────────
    if not table_exists("quiz_assignments"):
        op.create_table("quiz_assignments",
            sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type",             sa.Enum(name="assignment_type"), nullable=False),
            sa.Column("class_id",         postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("active",           sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("max_attempts",     sa.Integer(), nullable=False, server_default=sa.text("3")),
            sa.Column("expires_at",       sa.DateTime(timezone=True), nullable=True),
            sa.Column("require_identity", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("allow_guest",      sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_quiz_assignments_quiz_id",   "quiz_assignments", ["quiz_id"])
        op.create_index("ix_quiz_assignments_class_id",  "quiz_assignments", ["class_id"])

    if not table_exists("quiz_invites"):
        op.create_table("quiz_invites",
            sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_assignments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email",         sa.String(255), nullable=False),
            sa.Column("status",        sa.String(16),  nullable=False, server_default=sa.text("'INVITED'")),
            sa.Column("expires_at",    sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("assignment_id", "email", name="uq_invite_assignment_email"),
        )
        op.create_index("ix_quiz_invites_assignment_id", "quiz_invites", ["assignment_id"])
        op.create_index("ix_quiz_invites_email",         "quiz_invites", ["email"])

    if not table_exists("public_links"):
        op.create_table("public_links",
            sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_assignments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token",         sa.String(128), nullable=False, unique=True),
            sa.Column("expires_at",    sa.DateTime(timezone=True), nullable=True),
            sa.Column("allow_guest",   sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.UniqueConstraint("token", name="uq_public_link_token"),
        )
        op.create_index("ix_public_links_assignment_id", "public_links", ["assignment_id"])

    # ── GLOBAL QUIZ REQUESTS ───────────────────────────────────────────────────
    if not table_exists("global_quiz_requests"):
        op.create_table("global_quiz_requests",
            sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id",             postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by",        postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status",              sa.Enum(name="global_quiz_request_status"), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("is_active",           sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("requested_at",        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("reviewed_by",         postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at",         sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note",         sa.Text(), nullable=True),
            sa.Column("approved_public_slug",sa.String(80), nullable=True, unique=True),
            sa.UniqueConstraint("quiz_id", name="uq_global_quiz_request_quiz"),
        )
        op.create_index("ix_global_quiz_requests_status_active", "global_quiz_requests", ["status", "is_active"])

    # ── ATTEMPTS ───────────────────────────────────────────────────────────────
    if not table_exists("attempts"):
        op.create_table("attempts",
            sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("quiz_id",             postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("assignment_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_assignments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("class_id",            postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("participant_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("participant_email",   sa.String(255), nullable=True),
            sa.Column("participant_name",    sa.String(255), nullable=True),
            sa.Column("participant_role",    sa.String(30),  nullable=True),
            sa.Column("origin",              sa.Enum(name="attempt_origin"),  nullable=False, server_default=sa.text("'CLASS'")),
            sa.Column("global_request_id",   postgresql.UUID(as_uuid=True), sa.ForeignKey("global_quiz_requests.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status",              sa.Enum(name="attempt_status"), nullable=False, server_default=sa.text("'IN_PROGRESS'")),
            sa.Column("started_at",          sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("last_activity_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("expires_at",          sa.DateTime(timezone=True), nullable=True),
            sa.Column("submitted_at",        sa.DateTime(timezone=True), nullable=True),
            sa.Column("question_order_json", sa.JSON(), nullable=False),
            sa.Column("score_max",           sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("score_obtained",      sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_attempts_quiz_id",             "attempts", ["quiz_id"])
        op.create_index("ix_attempts_assignment_id",       "attempts", ["assignment_id"])
        op.create_index("ix_attempts_participant_user_id", "attempts", ["participant_user_id"])
        op.create_index("ix_attempts_participant_email",   "attempts", ["participant_email"])
        op.create_index("ix_attempts_status",              "attempts", ["status"])
        op.create_index("ix_attempts_origin",              "attempts", ["origin"])
        op.create_index("ix_attempts_global_request_id",  "attempts", ["global_request_id"])
        op.create_index("ix_attempt_quiz_user_status",     "attempts", ["quiz_id", "participant_user_id", "status"])

    if not table_exists("attempt_question_state"):
        op.create_table("attempt_question_state",
            sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("attempt_id",           postgresql.UUID(as_uuid=True), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_questions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("opened_at",            sa.DateTime(timezone=True), nullable=True),
            sa.Column("question_deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hints_used",           sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_locked",            sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question"),
        )
        op.create_index("ix_attempt_question_state_attempt_id", "attempt_question_state", ["attempt_id"])

    if not table_exists("answers"):
        op.create_table("answers",
            sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("attempt_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id",      postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_questions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("selected_option_id",postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_options.id", ondelete="SET NULL"), nullable=True),
            sa.Column("text_answer",      sa.Text(),    nullable=True),
            sa.Column("is_correct",       sa.Boolean(), nullable=True),
            sa.Column("points_awarded",   sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("answered_at",      sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_question"),
        )
        op.create_index("ix_answers_attempt_id",  "answers", ["attempt_id"])
        op.create_index("ix_answers_question_id", "answers", ["question_id"])

    # ── CHAT ───────────────────────────────────────────────────────────────────
    if not table_exists("chat_threads"):
        op.create_table("chat_threads",
            sa.Column("id",         postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_chat_threads_attempt_id", "chat_threads", ["attempt_id"])

    if not table_exists("chat_messages"):
        op.create_table("chat_messages",
            sa.Column("id",           postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("thread_id",    postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id",      postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("role",         sa.String(32), nullable=False),
            sa.Column("content",      sa.Text(),     nullable=False),
            sa.Column("out_of_scope", sa.Boolean(),  nullable=False, server_default=sa.text("false")),
            sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("deleted_at",   sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])

    # ── AUDIT / LOGS ───────────────────────────────────────────────────────────
    if not table_exists("audit_log"):
        op.create_table("audit_log",
            sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action",        sa.String(64), nullable=False),
            sa.Column("entity",        sa.String(64), nullable=False),
            sa.Column("entity_id",     sa.String(64), nullable=True),
            sa.Column("before",        sa.JSON(),     nullable=True),
            sa.Column("after",         sa.JSON(),     nullable=True),
            sa.Column("ip",            sa.String(64), nullable=True),
            sa.Column("user_agent",    sa.Text(),     nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_audit_log_actor_user_id",        "audit_log", ["actor_user_id"])
        op.create_index("ix_audit_log_action",               "audit_log", ["action"])
        op.create_index("ix_audit_log_entity",               "audit_log", ["entity"])
        op.create_index("ix_audit_action_entity_time",       "audit_log", ["action", "entity", "created_at"])

    if not table_exists("event_log"):
        op.create_table("event_log",
            sa.Column("id",         postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id",    postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event",      sa.String(64), nullable=False),
            sa.Column("meta",       sa.JSON(),     nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_event_log_user_id", "event_log", ["user_id"])
        op.create_index("ix_event_log_event",   "event_log", ["event"])

    if not table_exists("tutor_interactions"):
        op.create_table("tutor_interactions",
            sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("attempt_id",    postgresql.UUID(as_uuid=True), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id",   postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_questions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("kind",          sa.String(32), nullable=False),
            sa.Column("user_message",  sa.Text(),     nullable=True),
            sa.Column("tutor_message", sa.Text(),     nullable=True),
            sa.Column("out_of_scope",  sa.String(8),  nullable=False, server_default=sa.text("'false'")),
            sa.Column("meta",          sa.JSON(),     nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_tutor_interactions_attempt_id",  "tutor_interactions", ["attempt_id"])
        op.create_index("ix_tutor_interactions_question_id", "tutor_interactions", ["question_id"])

    # ── PASSWORD RESET TOKENS ──────────────────────────────────────────────────
    if not table_exists("password_reset_tokens"):
        op.create_table("password_reset_tokens",
            sa.Column("id",          postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id",     postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash",  sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at",  sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at",     sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index("ix_pwdreset_user_expires", "password_reset_tokens", ["user_id", "expires_at"])
        op.create_index("ix_pwdreset_token_hash",   "password_reset_tokens", ["token_hash"], unique=True)


def downgrade():
    # Drop in reverse dependency order
    tables = [
        "password_reset_tokens", "tutor_interactions", "event_log", "audit_log",
        "chat_messages", "chat_threads", "answers", "attempt_question_state", "attempts",
        "global_quiz_requests", "public_links", "quiz_invites", "quiz_assignments",
        "tutor_config", "quiz_options", "quiz_questions", "quizzes",
        "class_enrollments", "classes", "users",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    enums = [
        "global_quiz_request_status", "attempt_origin", "attempt_status",
        "assignment_type", "explain_policy", "tutor_scope", "tempo_mode",
        "quiz_mode", "quiz_status", "user_role",
    ]
    for e in enums:
        op.execute(f"DROP TYPE IF EXISTS {e}")

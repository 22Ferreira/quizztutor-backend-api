from sqlalchemy import text
from app.db.session import engine
from app.db.base import Base
# Import all models so SQLAlchemy registers them
from app.models import (  # noqa
    User, Class, ClassEnrollment,
    Quiz, QuizQuestion, QuizOption, TutorConfig,
    Assignment, QuizInvite, PublicLink,
    Attempt, AttemptQuestionState, Answer,
    ChatThread, ChatMessage,
    AuditLog, EventLog, TutorInteraction,
    PasswordResetToken,
    GlobalQuizRequest,

)

VIEWS_SQL = [
    """CREATE OR REPLACE VIEW vw_desempenho_aluno_questionario AS
    SELECT
      a.participant_user_id AS aluno_id,
      a.quiz_id,
      COUNT(*) FILTER (WHERE a.status IN ('SUBMITTED','EXPIRED')) AS tentativas_finalizadas,
      MAX(a.score_obtained) AS melhor_nota,
      AVG(a.score_obtained)::float AS media_nota,
      MAX(a.score_max) AS pontuacao_max
    FROM attempts a
    GROUP BY a.participant_user_id, a.quiz_id;""",

    """CREATE OR REPLACE VIEW vw_acertos_por_dificuldade AS
    SELECT
      a.participant_user_id AS aluno_id,
      a.quiz_id,
      qq.difficulty,
      COUNT(ans.id) AS total,
      COUNT(ans.id) FILTER (WHERE ans.is_correct = true) AS acertos
    FROM answers ans
    JOIN attempts a ON a.id = ans.attempt_id
    JOIN quiz_questions qq ON qq.id = ans.question_id
    GROUP BY a.participant_user_id, a.quiz_id, qq.difficulty;""",

    """CREATE OR REPLACE VIEW vw_tempo_medio_por_questao AS
    SELECT
      a.quiz_id,
      s.question_id,
      AVG(EXTRACT(EPOCH FROM (COALESCE(ans.answered_at, a.last_activity_at) - s.opened_at)))::float AS tempo_medio_seg
    FROM attempt_question_state s
    JOIN attempts a ON a.id = s.attempt_id
    LEFT JOIN answers ans ON ans.attempt_id = s.attempt_id AND ans.question_id = s.question_id
    WHERE s.opened_at IS NOT NULL
    GROUP BY a.quiz_id, s.question_id;""",

    """CREATE OR REPLACE VIEW vw_tempo_medio_por_dificuldade AS
    SELECT
      a.quiz_id,
      qq.difficulty,
      AVG(EXTRACT(EPOCH FROM (COALESCE(ans.answered_at, a.last_activity_at) - s.opened_at)))::float AS tempo_medio_seg
    FROM attempt_question_state s
    JOIN attempts a ON a.id = s.attempt_id
    JOIN quiz_questions qq ON qq.id = s.question_id
    LEFT JOIN answers ans ON ans.attempt_id = s.attempt_id AND ans.question_id = s.question_id
    WHERE s.opened_at IS NOT NULL
    GROUP BY a.quiz_id, qq.difficulty;""",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in VIEWS_SQL:
            await conn.execute(text(sql))

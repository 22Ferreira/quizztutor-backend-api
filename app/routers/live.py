"""
Router do módulo Sala Ao Vivo (Live Quiz Session)
Prefixo: /live

Endpoints:
  Professor:
    POST   /live/sessions                   — criar sessão
    GET    /live/sessions                   — listar sessões do professor
    GET    /live/sessions/{id}/state        — estado completo (reconexão)
    POST   /live/sessions/{id}/start        — iniciar
    POST   /live/sessions/{id}/end          — encerrar
    GET    /live/sessions/{id}/scoreboard   — ranking
    GET    /live/sessions/{id}/summary      — resumo + alertas
    GET    /live/sessions/{id}/question-stats — análise por questão
    GET    /live/sessions/{id}/progress     — distribuição de progresso
    POST   /live/sessions/{id}/approve/{user_id}
    POST   /live/sessions/{id}/kick/{user_id}
    POST   /live/sessions/{id}/ban/{user_id}
    WebSocket /live/sessions/{id}/ws/professor

  Aluno:
    GET    /live/join/{code}                — buscar sessão pelo código
    POST   /live/sessions/{id}/join         — entrar na sessão
    POST   /live/sessions/{id}/heartbeat    — manter conexão viva
    GET    /live/sessions/{id}/question     — questão atual
    POST   /live/sessions/{id}/answer       — responder
    GET    /live/sessions/{id}/result       — resultado final do aluno
    WebSocket /live/sessions/{id}/ws/student
"""

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.models.live_session import (
    LiveSession, LiveParticipant, LiveAttempt, LiveAnswer,
    LiveSessionStatus, LiveParticipantStatus, LiveAnswerReason,
)
from app.models.quiz import Quiz, QuizQuestion, QuizOption, QuizStatus
from app.models.classroom import ClassEnrollment
from app.utils.rbac import get_current_user, require_roles, resolve_user_from_token_string
from app.schemas.live_schemas import (
    LiveSessionCreate, LiveSessionOut, ParticipantOut,
    LiveQuestionOut, LiveAnswerIn, LiveAnswerOut,
    ScoreboardOut, ScoreboardEntry, SessionSummaryOut,
    QuestionStatsOut, ProgressDistributionOut, SessionStateOut,
    KickBanIn,
)

router = APIRouter(prefix="/live", tags=["live"])

# ── WebSocket manager ──────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # session_id -> list of websockets (professor)
        self._prof: dict[str, list[WebSocket]] = {}
        # session_id -> {user_id: websocket} (students)
        self._students: dict[str, dict[str, WebSocket]] = {}

    async def connect_prof(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._prof.setdefault(session_id, []).append(ws)

    async def connect_student(self, session_id: str, user_id: str, ws: WebSocket):
        await ws.accept()
        self._students.setdefault(session_id, {})[user_id] = ws

    def disconnect_prof(self, session_id: str, ws: WebSocket):
        conns = self._prof.get(session_id, [])
        if ws in conns:
            conns.remove(ws)

    def disconnect_student(self, session_id: str, user_id: str):
        self._students.get(session_id, {}).pop(user_id, None)

    async def broadcast_prof(self, session_id: str, data: dict):
        dead = []
        for ws in self._prof.get(session_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_prof(session_id, ws)

    async def send_student(self, session_id: str, user_id: str, data: dict):
        ws = self._students.get(session_id, {}).get(user_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect_student(session_id, user_id)

    async def broadcast_all(self, session_id: str, data: dict):
        await self.broadcast_prof(session_id, data)
        dead = []
        for uid, ws in self._students.get(session_id, {}).items():
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect_student(session_id, uid)


manager = ConnectionManager()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    return str(random.randint(100000, 999999))


def _shuffle_with_seed(items: list, seed: int) -> list:
    r = random.Random(seed)
    shuffled = items[:]
    r.shuffle(shuffled)
    return shuffled


async def _get_session_or_404(session_id: uuid.UUID, db: AsyncSession) -> LiveSession:
    r = await db.execute(select(LiveSession).where(LiveSession.id == session_id))
    sess = r.scalar_one_or_none()
    if not sess:
        raise HTTPException(404, "Sessão não encontrada")
    return sess


async def _get_participant_or_404(session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> LiveParticipant:
    r = await db.execute(
        select(LiveParticipant).where(
            LiveParticipant.session_id == session_id,
            LiveParticipant.user_id == user_id,
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Participante não encontrado nesta sessão")
    return p


async def _build_scoreboard(session_id: uuid.UUID, db: AsyncSession) -> ScoreboardOut:
    r = await db.execute(
        select(LiveAttempt).where(LiveAttempt.session_id == session_id)
    )
    attempts = r.scalars().all()

    # Buscar total de questões
    sess_r = await db.execute(select(LiveSession).where(LiveSession.id == session_id))
    sess = sess_r.scalar_one_or_none()
    quiz_r = await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == sess.quiz_id))
    total_q = len(quiz_r.scalars().all())

    # Buscar participantes para pegar status
    part_r = await db.execute(select(LiveParticipant).where(LiveParticipant.session_id == session_id))
    parts = {p.user_id: p for p in part_r.scalars().all()}

    entries = []
    for att in attempts:
        part = parts.get(att.user_id)
        # Expulsos/banidos não contam mais como participantes válidos do
        # ranking — senão o rank/total ficava incluindo gente que já saiu.
        if part and part.status in (LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED):
            continue
        answered = att.answered_count or 0
        correct  = att.correct_count or 0
        accuracy = (correct / answered * 100) if answered > 0 else 0.0
        avg_ms   = (att.total_time_ms / answered) if answered > 0 else 0.0
        status   = part.status.value if part else "UNKNOWN"

        # último resultado
        last_result = None
        if att.answers:
            last_ans = sorted(att.answers, key=lambda a: a.answered_at)[-1]
            if last_ans.reason in (LiveAnswerReason.TIMEOUT, LiveAnswerReason.DISCONNECT_TIMEOUT):
                last_result = "timeout"
            elif last_ans.is_correct:
                last_result = "correct"
            else:
                last_result = "wrong"

        entries.append(ScoreboardEntry(
            rank=0,  # calculado abaixo
            user_id=att.user_id,
            user_name=part.user.name if part and part.user else "?",
            correct_count=correct,
            answered_count=answered,
            accuracy=round(accuracy, 1),
            total_time_ms=att.total_time_ms or 0,
            avg_time_ms=round(avg_ms, 1),
            current_question_number=att.current_question_index + 1,
            total_questions=total_q,
            status=status,
            last_result=last_result,
        ))

    # Ordenação oficial: acertos DESC, accuracy DESC, answered DESC, tempo ASC
    entries.sort(key=lambda e: (-e.correct_count, -e.accuracy, -e.answered_count, e.total_time_ms))
    for i, e in enumerate(entries):
        e.rank = i + 1

    return ScoreboardOut(entries=entries, updated_at=_now())


async def _build_question_stats(session_id: uuid.UUID, db: AsyncSession, sess=None) -> list[QuestionStatsOut]:
    # Buscar todas as respostas com attempt carregado via join explícito
    r = await db.execute(
        select(LiveAnswer, LiveAttempt.user_id)
        .join(LiveAttempt, LiveAnswer.attempt_id == LiveAttempt.id)
        .where(LiveAttempt.session_id == session_id)
    )
    rows = r.all()  # lista de (LiveAnswer, user_id)

    # Buscar nomes dos participantes
    parts_r = await db.execute(
        select(LiveParticipant)
        .where(LiveParticipant.session_id == session_id)
        .options()
    )
    parts_list = parts_r.scalars().all()
    # user_id → name
    uid_to_name: dict[uuid.UUID, str] = {
        p.user_id: (p.user.name if p.user else str(p.user_id)) for p in parts_list
    }

    stats: dict[uuid.UUID, dict] = {}
    for ans, att_uid in rows:
        qid = ans.question_id
        if qid not in stats:
            stats[qid] = {"total": 0, "correct": 0, "times": [], "options": {},
                          "correct_users": [], "wrong_users": []}
        stats[qid]["total"] += 1
        if ans.is_correct:
            stats[qid]["correct"] += 1
            if att_uid:
                stats[qid]["correct_users"].append({
                    "user_id": str(att_uid),
                    "name": uid_to_name.get(att_uid, "?"),
                })
        else:
            if att_uid and ans.reason != LiveAnswerReason.TIMEOUT:
                stats[qid]["wrong_users"].append({
                    "user_id": str(att_uid),
                    "name": uid_to_name.get(att_uid, "?"),
                    "timeout": False,
                })
            elif att_uid:
                stats[qid]["wrong_users"].append({
                    "user_id": str(att_uid),
                    "name": uid_to_name.get(att_uid, "?"),
                    "timeout": True,
                })
        stats[qid]["times"].append(ans.response_time_ms)
        if ans.selected_option_id:
            oid = str(ans.selected_option_id)
            stats[qid]["options"][oid] = stats[qid]["options"].get(oid, 0) + 1

    # Buscar ordem das questões a partir de uma tentativa para saber o índice original
    any_att_r = await db.execute(
        select(LiveAttempt).where(LiveAttempt.session_id == session_id).limit(1)
    )
    any_att = any_att_r.scalar_one_or_none()
    question_order = [str(qid) for qid in (any_att.question_order if any_att else [])]

    result = []
    for qid, s in stats.items():
        q_r = await db.execute(select(QuizQuestion).where(QuizQuestion.id == qid))
        q = q_r.scalar_one_or_none()
        avg_ms = sum(s["times"]) / len(s["times"]) if s["times"] else 0
        most_chosen = max(s["options"], key=s["options"].get) if s["options"] else None
        # Índice original da questão (posição no quiz, 1-based)
        try:
            original_index = question_order.index(str(qid)) + 1
        except ValueError:
            original_index = None

        # Dificuldade só é exibida quando a sessão usa BY_DIFF; fora disso, o campo
        # difficulty da questão é só um default de banco (não configurado para esta sessão)
        difficulty = None
        if sess and sess.time_by_difficulty:
            difficulty = (sess.time_by_difficulty.get("overrides") or {}).get(str(qid))
            if not difficulty and q:
                difficulty = q.difficulty

        result.append(QuestionStatsOut(
            question_id=qid,
            statement_preview=(q.statement[:80] + "...") if q and len(q.statement) > 80 else (q.statement if q else ""),
            total_answers=s["total"],
            correct_count=s["correct"],
            wrong_count=s["total"] - s["correct"],
            accuracy_pct=round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0,
            avg_time_ms=round(avg_ms, 1),
            most_chosen_option_id=uuid.UUID(most_chosen) if most_chosen else None,
            question_index=original_index,
            difficulty=difficulty,
            correct_users=s["correct_users"],
            wrong_users=s["wrong_users"],
        ))

    # Questões que ainda não tiveram NENHUMA resposta ficavam de fora da
    # lista inteira (o loop acima só cria uma entrada em "stats" quando
    # existe pelo menos uma LiveAnswer) — não apareciam nem com
    # total_answers=0, simplesmente não existiam no resultado. Isso fazia
    # o filtro "Sem resposta" do painel do professor nunca achar nada,
    # mesmo quando uma questão de verdade não tinha sido respondida.
    answered_qids = {str(qid) for qid in stats.keys()}
    for idx, qid_str in enumerate(question_order):
        if qid_str in answered_qids:
            continue
        try:
            qid_uuid = uuid.UUID(qid_str)
        except ValueError:
            continue
        q_r = await db.execute(select(QuizQuestion).where(QuizQuestion.id == qid_uuid))
        q = q_r.scalar_one_or_none()
        if not q:
            continue
        difficulty = None
        if sess and sess.time_by_difficulty:
            difficulty = (sess.time_by_difficulty.get("overrides") or {}).get(qid_str)
            if not difficulty:
                difficulty = q.difficulty
        result.append(QuestionStatsOut(
            question_id=qid_uuid,
            statement_preview=(q.statement[:80] + "...") if len(q.statement) > 80 else q.statement,
            total_answers=0,
            correct_count=0,
            wrong_count=0,
            accuracy_pct=0.0,
            avg_time_ms=0.0,
            most_chosen_option_id=None,
            question_index=idx + 1,
            difficulty=difficulty,
            correct_users=[],
            wrong_users=[],
        ))

    # Ordena pelo índice original da questão no quiz
    result.sort(key=lambda x: x.question_index or 999)
    return result


def _get_question_seconds(sess, question) -> int | None:
    """Retorna o tempo em segundos para a questão atual.
    Prioridade:
      1. time_by_difficulty + dificuldade da questão (BY_DIFF)
      2. per_question_seconds (PER_QUESTION / MIXED)
      3. None (sem timer por questão)
    """
    if sess.time_by_difficulty:
        tbd = sess.time_by_difficulty

        # Normaliza chaves do dicionário para pt-BR (FACIL/MEDIA/DIFICIL)
        # Suporta tanto inglês (EASY/MEDIUM/HARD) quanto português
        EN_TO_PT = {"EASY": "FACIL", "MEDIUM": "MEDIA", "HARD": "DIFICIL"}

        def normalize(d: str | None) -> str | None:
            if not d:
                return None
            d = d.upper()
            return EN_TO_PT.get(d, d)  # converte se for inglês, senão mantém

        # Buscar dificuldade: override por questão > dificuldade padrão da questão
        overrides = tbd.get("overrides", {})
        raw_diff = overrides.get(str(question.id)) if question else None
        if not raw_diff and question:
            raw_diff = question.difficulty

        diff = normalize(raw_diff) or "MEDIA"

        # Buscar tempo: tenta a chave normalizada, depois fallback inglês
        seconds = tbd.get(diff)
        if seconds is None:
            # fallback: tenta inglês caso o dict tenha sido salvo com chaves en
            PT_TO_EN = {"FACIL": "EASY", "MEDIA": "MEDIUM", "DIFICIL": "HARD"}
            seconds = tbd.get(PT_TO_EN.get(diff, diff))
        if seconds:
            return int(seconds)

    if sess.per_question_seconds:
        return int(sess.per_question_seconds)
    return None


async def _check_and_expire_question(attempt: LiveAttempt, db: AsyncSession) -> bool:
    """Verifica se o tempo da questão expirou. Registra timeout se necessário. Retorna True se expirou."""
    if not attempt.question_deadline_at:
        return False
    now = _now()
    if attempt.question_deadline_at.replace(tzinfo=timezone.utc) > now:
        return False

    # Registrar timeout da questão
    q_id = attempt.question_order[attempt.current_question_index] if attempt.current_question_index < len(attempt.question_order) else None
    if q_id:
        existing = await db.execute(
            select(LiveAnswer).where(
                LiveAnswer.attempt_id == attempt.id,
                LiveAnswer.question_id == uuid.UUID(q_id),
            )
        )
        if not existing.scalar_one_or_none():
            db.add(LiveAnswer(
                attempt_id=attempt.id,
                question_id=uuid.UUID(q_id),
                is_correct=False,
                response_time_ms=0,
                reason=LiveAnswerReason.TIMEOUT,  # motivo correto: tempo da questão
            ))
            # UPDATE atômico para evitar stale read
            await db.execute(
                update(LiveAttempt)
                .where(LiveAttempt.id == attempt.id)
                .values(
                    answered_count=LiveAttempt.answered_count + 1,
                    current_question_index=LiveAttempt.current_question_index + 1,
                    question_started_at=None,
                    question_deadline_at=None,
                )
            )
            await db.refresh(attempt)

    # NÃO marcar como PAUSED — expiração de questão não é desconexão,
    # apenas avança para a próxima questão automaticamente
    await db.commit()
    return True


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — PROFESSOR
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/sessions", summary="Criar sala ao vivo")
async def create_session(
    body: LiveSessionCreate,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    # Valida quiz: deve ser PUBLISHED e do professor
    q_r = await db.execute(select(Quiz).where(Quiz.id == body.quiz_id))
    quiz = q_r.scalar_one_or_none()
    if not quiz:
        raise HTTPException(404, "Quiz não encontrado")
    if quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(400, "Apenas quizzes publicados podem ser usados em salas ao vivo")
    if str(quiz.professor_id) != str(me.id):
        raise HTTPException(403, "Você só pode usar seus próprios quizzes")

    # Gera código único
    for _ in range(10):
        code = _generate_code()
        existing = await db.execute(select(LiveSession).where(LiveSession.session_code == code))
        if not existing.scalar_one_or_none():
            break

    session = LiveSession(
        quiz_id=body.quiz_id,
        classroom_id=body.classroom_id,
        created_by=me.id,
        session_code=code,
        entry_policy=body.entry_policy,
        allow_late_join=body.allow_late_join,
        allow_rejoin=body.allow_rejoin,
        single_approval=body.single_approval,
        shuffle_questions=body.shuffle_questions,
        shuffle_options=body.shuffle_options,
        show_ranking_students=body.show_ranking_students,
        show_answer_immediate=body.show_answer_immediate,
        disable_hints=body.disable_hints,
        disable_chat=body.disable_chat,
        time_mode=body.time_mode,
        total_time_seconds=body.total_time_seconds,
        per_question_seconds=body.per_question_seconds,
        time_by_difficulty=body.time_by_difficulty,
        scoring_mode=body.scoring_mode,
        max_participants=body.max_participants,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {
        "id": str(session.id),
        "session_code": session.session_code,
        "status": session.status.value,
        "quiz_title": quiz.title,
    }


@router.get("/sessions", summary="Listar sessões do professor")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    r = await db.execute(
        select(LiveSession)
        .where(LiveSession.created_by == me.id)
        .order_by(LiveSession.created_at.desc())
        .limit(50)
    )
    sessions = r.scalars().all()
    result = []
    for s in sessions:
        result.append({
            "id": str(s.id),
            "quiz_title": s.quiz.title if s.quiz else "",
            "status": s.status.value,
            "session_code": s.session_code,
            "created_at": s.created_at.isoformat(),
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        })
    return result


@router.get("/sessions/{session_id}/lobby-participants", summary="Participantes do lobby (professor)")
async def get_lobby_participants(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    """
    Endpoint leve para o professor acompanhar participantes no lobby em tempo real.
    Retorna apenas dados dos participantes, sem scoreboard nem q_stats pesados.
    """
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403, "Não autorizado")

    p_r = await db.execute(
        select(LiveParticipant).where(
            LiveParticipant.session_id == session_id,
            LiveParticipant.status.notin_([LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED]),
        )
    )
    participants = p_r.scalars().all()

    online  = sum(1 for p in participants if p.status in (LiveParticipantStatus.RUNNING, LiveParticipantStatus.WAITING) and p.approved)
    pending = sum(1 for p in participants if not p.approved)
    total   = len(participants)

    return {
        "session_status": sess.status.value,
        "session_code": sess.session_code,
        "online_count": online,
        "pending_count": pending,
        "total_count": total,
        "participants": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "user_name": p.user.name if p.user else "?",
                "status": p.status.value,
                "approved": p.approved,
                "joined_at": p.joined_at.isoformat(),
            }
            for p in participants
        ],
    }


@router.get("/sessions/{session_id}/state", summary="Estado completo da sessão (reconexão professor)")
async def get_session_state(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403, "Não autorizado")

    scoreboard = await _build_scoreboard(session_id, db)
    q_stats    = await _build_question_stats(session_id, db, sess)

    # Participantes
    p_r = await db.execute(select(LiveParticipant).where(LiveParticipant.session_id == session_id))
    participants = p_r.scalars().all()

    # Distribuição de progresso
    progress_dist = {}
    for entry in scoreboard.entries:
        idx = entry.current_question_number
        progress_dist[idx] = progress_dist.get(idx, 0) + 1

    # Contagem de status
    online    = sum(1 for p in participants if p.status in (LiveParticipantStatus.RUNNING, LiveParticipantStatus.WAITING))
    offline   = sum(1 for p in participants if p.status == LiveParticipantStatus.DISCONNECTED)
    finished  = sum(1 for p in participants if p.status == LiveParticipantStatus.FINISHED)
    total     = len(participants)

    # Médias
    valid = [e for e in scoreboard.entries if e.answered_count > 0]
    avg_acc  = sum(e.accuracy for e in valid) / len(valid) if valid else 0
    avg_prog = sum(e.answered_count / e.total_questions for e in scoreboard.entries) / len(scoreboard.entries) if scoreboard.entries else 0
    avg_time = sum(e.avg_time_ms for e in valid) / len(valid) if valid else 0

    # Tempo restante
    time_remaining = None
    if sess.status == LiveSessionStatus.RUNNING and sess.started_at and sess.total_time_seconds:
        elapsed = (_now() - sess.started_at.replace(tzinfo=timezone.utc)).total_seconds()
        time_remaining = max(0, int(sess.total_time_seconds - elapsed))

    return {
        "session": {
            "id": str(sess.id),
            "quiz_title": sess.quiz.title if sess.quiz else "",
            "status": sess.status.value,
            "session_code": sess.session_code,
            "time_mode": sess.time_mode.value,
            "total_time_seconds": sess.total_time_seconds,
            "per_question_seconds": sess.per_question_seconds,
            "shuffle_questions": sess.shuffle_questions,
            "shuffle_options": sess.shuffle_options,
            "show_ranking_students": sess.show_ranking_students,
            "show_answer_immediate": sess.show_answer_immediate,
            "disable_hints": sess.disable_hints,
            "disable_chat": sess.disable_chat,
            "entry_policy": sess.entry_policy.value,
            "started_at": sess.started_at.isoformat() if sess.started_at else None,
            "time_by_difficulty": sess.time_by_difficulty,  # None se BY_DIFF não configurado
        },
        "summary": {
            "total_participants": total,
            "online_count": online,
            "offline_count": offline,
            "finished_count": finished,
            "avg_accuracy": round(avg_acc, 1),
            "avg_progress_pct": round(avg_prog * 100, 1),
            "avg_time_per_question_ms": round(avg_time, 1),
            "time_remaining_seconds": time_remaining,
        },
        "scoreboard": scoreboard.dict(),
        "question_stats": [s.dict() for s in q_stats],
        "progress_distribution": [{"question": k, "count": v} for k, v in sorted(progress_dist.items())],
        "participants": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "user_name": p.user.name if p.user else "?",
                "status": p.status.value,
                "approved": p.approved,
                "joined_at": p.joined_at.isoformat(),
                "last_seen_at": p.last_seen_at.isoformat(),
                "disconnect_count": p.disconnect_count,
            }
            for p in participants
        ],
    }


@router.post("/sessions/{session_id}/start", summary="Iniciar sessão")
async def start_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403, "Não autorizado")
    if sess.status != LiveSessionStatus.LOBBY:
        raise HTTPException(400, f"Sessão já está {sess.status.value}")

    sess.status = LiveSessionStatus.RUNNING
    sess.started_at = _now()
    await db.commit()

    await manager.broadcast_all(str(session_id), {"type": "SESSION_STARTED"})
    return {"ok": True, "started_at": sess.started_at.isoformat()}


@router.post("/sessions/{session_id}/end", summary="Encerrar sessão")
async def end_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403, "Não autorizado")
    if sess.status == LiveSessionStatus.ENDED:
        raise HTTPException(400, "Sessão já encerrada")

    sess.status = LiveSessionStatus.ENDED
    sess.ended_at = _now()

    # Finaliza todos os participantes ainda ativos
    p_r = await db.execute(select(LiveParticipant).where(
        LiveParticipant.session_id == session_id,
        LiveParticipant.status.in_([LiveParticipantStatus.RUNNING, LiveParticipantStatus.WAITING, LiveParticipantStatus.DISCONNECTED, LiveParticipantStatus.PAUSED])
    ))
    for p in p_r.scalars().all():
        p.status = LiveParticipantStatus.FINISHED

    await db.commit()
    await manager.broadcast_all(str(session_id), {"type": "SESSION_ENDED"})
    return {"ok": True, "ended_at": sess.ended_at.isoformat()}




@router.delete("/sessions/{session_id}", summary="Apagar sessão encerrada")
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403, "Não autorizado")
    if sess.status != LiveSessionStatus.ENDED:
        raise HTTPException(400, "Só é possível apagar sessões encerradas")

    # Apaga em cascata: respostas → tentativas → participantes → sessão
    # LiveAnswer
    att_r = await db.execute(select(LiveAttempt).where(LiveAttempt.session_id == session_id))
    for att in att_r.scalars().all():
        ans_r = await db.execute(select(LiveAnswer).where(LiveAnswer.attempt_id == att.id))
        for ans in ans_r.scalars().all():
            await db.delete(ans)
        await db.delete(att)

    # Participantes
    part_r = await db.execute(select(LiveParticipant).where(LiveParticipant.session_id == session_id))
    for p in part_r.scalars().all():
        await db.delete(p)

    await db.delete(sess)
    await db.commit()
    return {"ok": True}

@router.get("/sessions/{session_id}/scoreboard", summary="Ranking ao vivo")
async def get_scoreboard(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sess = await _get_session_or_404(session_id, db)
    # Aluno só vê se professor permitiu
    if me.role.value == "ALUNO" and not sess.show_ranking_students:
        raise HTTPException(403, "Ranking não disponível para alunos nesta sessão")
    scoreboard = await _build_scoreboard(session_id, db)
    return scoreboard.dict()


@router.get("/sessions/{session_id}/question-stats", summary="Estatísticas por questão")
async def get_question_stats(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403)
    stats = await _build_question_stats(session_id, db, sess)
    return [s.dict() for s in stats]


@router.post("/sessions/{session_id}/approve/{user_id}", summary="Aprovar aluno")
async def approve_participant(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403)
    part = await _get_participant_or_404(session_id, user_id, db)
    part.approved = True
    if sess.status == LiveSessionStatus.RUNNING:
        part.status = LiveParticipantStatus.RUNNING
    await db.commit()
    await manager.send_student(str(session_id), str(user_id), {"type": "APPROVED"})
    await manager.broadcast_prof(str(session_id), {
        "type": "PARTICIPANT_APPROVED",
        "user_id": str(user_id),
    })
    return {"ok": True}


@router.post("/sessions/{session_id}/kick/{user_id}", summary="Expulsar aluno")
async def kick_participant(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    body: KickBanIn = KickBanIn(),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403)
    part = await _get_participant_or_404(session_id, user_id, db)
    part.status = LiveParticipantStatus.KICKED
    part.kicked_at = _now()
    await db.commit()
    await manager.send_student(str(session_id), str(user_id), {"type": "KICKED", "reason": body.reason})
    return {"ok": True}


@router.post("/sessions/{session_id}/ban/{user_id}", summary="Banir aluno")
async def ban_participant(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    body: KickBanIn = KickBanIn(),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require_roles("PROFESSOR", "ADMIN")),
):
    sess = await _get_session_or_404(session_id, db)
    if str(sess.created_by) != str(me.id):
        raise HTTPException(403)
    part = await _get_participant_or_404(session_id, user_id, db)
    part.status = LiveParticipantStatus.BANNED
    part.banned_at = _now()
    await db.commit()
    await manager.send_student(str(session_id), str(user_id), {"type": "BANNED", "reason": body.reason})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — ALUNO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/join/{code}", summary="Buscar sessão pelo código PIN")
async def find_session_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    r = await db.execute(
        select(LiveSession).where(
            LiveSession.session_code == code,
            LiveSession.status.in_([LiveSessionStatus.LOBBY, LiveSessionStatus.RUNNING]),
        )
    )
    sess = r.scalar_one_or_none()
    if not sess:
        raise HTTPException(404, "Sala não encontrada ou já encerrada")
    return {
        "id": str(sess.id),
        "quiz_title": sess.quiz.title if sess.quiz else "",
        "status": sess.status.value,
        "entry_policy": sess.entry_policy.value,
        "session_code": sess.session_code,
    }


@router.post("/sessions/{session_id}/join", summary="Entrar na sessão")
async def join_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sess = await _get_session_or_404(session_id, db)

    if sess.status == LiveSessionStatus.ENDED:
        raise HTTPException(400, "Sessão encerrada")
    if sess.status == LiveSessionStatus.RUNNING and not sess.allow_late_join:
        raise HTTPException(400, "Entrada após início não permitida nesta sessão")

    # Verifica se já é participante
    existing_r = await db.execute(
        select(LiveParticipant).where(
            LiveParticipant.session_id == session_id,
            LiveParticipant.user_id == me.id,
        )
    )
    existing = existing_r.scalar_one_or_none()

    if existing:
        if existing.status == LiveParticipantStatus.BANNED:
            raise HTTPException(403, "Você foi banido desta sessão")
        if existing.status == LiveParticipantStatus.KICKED and not sess.allow_rejoin:
            raise HTTPException(403, "Reconexão não permitida nesta sessão")
        # Reconectar
        if existing.status in (LiveParticipantStatus.DISCONNECTED, LiveParticipantStatus.KICKED):
            # Sem aprovação única: toda nova entrada volta para a fila de aprovação,
            # mesmo de um aluno que já tinha sido aprovado antes.
            if sess.entry_policy.value == "APPROVAL_REQUIRED" and not sess.single_approval:
                existing.approved = False
                existing.status = LiveParticipantStatus.WAITING
            else:
                existing.status = LiveParticipantStatus.WAITING if sess.status == LiveSessionStatus.LOBBY else LiveParticipantStatus.RUNNING
            existing.last_seen_at = _now()
            await db.commit()
        return {
            "ok": True,
            "participant_id": str(existing.id),
            "status": existing.status.value,
            "approved": existing.approved,
        }

    # Verifica política de entrada
    approved = True
    if sess.entry_policy.value == "ONLY_CLASSROOM":
        if not sess.classroom_id:
            raise HTTPException(400, "Sessão restrita a turma mas sem turma configurada")
        enroll_r = await db.execute(
            select(ClassEnrollment).where(
                ClassEnrollment.class_id == sess.classroom_id,
                ClassEnrollment.user_id == me.id,
                ClassEnrollment.status == "ACTIVE",
            )
        )
        if not enroll_r.scalar_one_or_none():
            raise HTTPException(403, "Você não está matriculado nesta turma")
    elif sess.entry_policy.value == "APPROVAL_REQUIRED":
        approved = False

    # Verifica limite de participantes
    if sess.max_participants:
        count_r = await db.execute(
            select(func.count()).select_from(LiveParticipant).where(
                LiveParticipant.session_id == session_id,
                LiveParticipant.status.notin_([LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED])
            )
        )
        count = count_r.scalar()
        if count >= sess.max_participants:
            raise HTTPException(400, "Sala cheia")

    initial_status = LiveParticipantStatus.WAITING
    if approved and sess.status == LiveSessionStatus.RUNNING:
        initial_status = LiveParticipantStatus.RUNNING

    part = LiveParticipant(
        session_id=session_id,
        user_id=me.id,
        approved=approved,
        status=initial_status,
    )
    db.add(part)
    await db.commit()
    await db.refresh(part)

    # Notificar professor
    await manager.broadcast_prof(str(session_id), {
        "type": "PARTICIPANT_JOINED",
        "user_id": str(me.id),
        "user_name": me.name,
        "approved": approved,
        "status": initial_status.value,
    })

    return {
        "ok": True,
        "participant_id": str(part.id),
        "status": part.status.value,
        "approved": part.approved,
        "message": "Aguardando aprovação do professor" if not approved else "Você entrou na sala",
    }


@router.post("/sessions/{session_id}/heartbeat", summary="Heartbeat do aluno")
async def heartbeat(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    part = await _get_participant_or_404(session_id, me.id, db)

    if part.status in (LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED):
        return {"ok": False, "status": part.status.value}

    was_disconnected = part.status == LiveParticipantStatus.DISCONNECTED
    part.last_seen_at = _now()

    # Reconexão automática de DISCONNECTED -> RUNNING (se sessão ainda rodando)
    if was_disconnected:
        sess_r = await db.execute(select(LiveSession).where(LiveSession.id == session_id))
        sess = sess_r.scalar_one_or_none()
        if sess and sess.status == LiveSessionStatus.RUNNING:
            part.status = LiveParticipantStatus.RUNNING
            part.disconnect_count += 1

            # Se estava PAUSED aguardando reconexão, retomar questão
            att_r = await db.execute(
                select(LiveAttempt).where(
                    LiveAttempt.session_id == session_id,
                    LiveAttempt.user_id == me.id,
                )
            )
            att = att_r.scalar_one_or_none()
            if att and att.paused_waiting_reconnect:
                att.paused_waiting_reconnect = False
                # Inicia tempo da próxima questão após reconexão
                if att.current_question_index < len(att.question_order):
                    rc_q_id = uuid.UUID(att.question_order[att.current_question_index])
                    rc_q_r  = await db.execute(select(QuizQuestion).where(QuizQuestion.id == rc_q_id))
                    rc_q    = rc_q_r.scalar_one_or_none()
                    rc_secs = _get_question_seconds(sess, rc_q)
                    if rc_secs:
                        att.question_started_at = _now()
                        deadline = _now() + timedelta(seconds=rc_secs)
                        if sess.total_time_seconds and sess.started_at:
                            session_deadline = sess.started_at.replace(tzinfo=timezone.utc) + timedelta(seconds=sess.total_time_seconds)
                            deadline = min(deadline, session_deadline)
                        att.question_deadline_at = deadline

            await manager.broadcast_prof(str(session_id), {
                "type": "PARTICIPANT_RECONNECTED",
                "user_id": str(me.id),
            })

    await db.commit()
    return {"ok": True, "status": part.status.value}


@router.get("/sessions/{session_id}/lobby-status", summary="Status do lobby para o aluno")
async def get_lobby_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """
    Endpoint acessível ao aluno durante a espera no lobby.
    Retorna: status da sessão, aprovação do aluno e lista básica de participantes.
    """
    sess = await _get_session_or_404(session_id, db)

    # Verifica se o aluno é participante
    part_r = await db.execute(
        select(LiveParticipant).where(
            LiveParticipant.session_id == session_id,
            LiveParticipant.user_id == me.id,
        )
    )
    part = part_r.scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Você não está nesta sessão")

    # Lista de participantes aprovados (apenas nome + status — sem dados sensíveis)
    all_parts_r = await db.execute(
        select(LiveParticipant).where(
            LiveParticipant.session_id == session_id,
            LiveParticipant.status.notin_([
                LiveParticipantStatus.KICKED,
                LiveParticipantStatus.BANNED,
            ]),
        )
    )
    all_parts = all_parts_r.scalars().all()

    participants = [
        {
            "user_id": str(p.user_id),
            "user_name": p.user.name if p.user else "?",
            "status": p.status.value,
        }
        for p in all_parts
    ]

    return {
        "session_status": sess.status.value,
        "approved": part.approved,
        "my_status": part.status.value,
        "participants": participants,
        "config": {
            "show_ranking_students": sess.show_ranking_students,
            "show_answer_immediate": sess.show_answer_immediate,
            "disable_hints": sess.disable_hints,
            "disable_chat": sess.disable_chat,
            "time_mode": sess.time_mode.value,
            "per_question_seconds": sess.per_question_seconds,
            "total_time_seconds": sess.total_time_seconds,
        },
    }


@router.get("/sessions/{session_id}/question", summary="Questão atual do aluno")
async def get_current_question(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sess = await _get_session_or_404(session_id, db)
    if sess.status == LiveSessionStatus.LOBBY:
        raise HTTPException(400, "Sessão ainda não iniciou")
    if sess.status == LiveSessionStatus.ENDED:
        raise HTTPException(400, "Sessão encerrada")

    part = await _get_participant_or_404(session_id, me.id, db)
    if part.status in (LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED):
        raise HTTPException(403, f"Você foi {part.status.value.lower()}")
    if not part.approved:
        raise HTTPException(400, "Aguardando aprovação do professor")

    # Buscar ou criar tentativa
    att_r = await db.execute(
        select(LiveAttempt).where(
            LiveAttempt.session_id == session_id,
            LiveAttempt.user_id == me.id,
        )
    )
    att = att_r.scalar_one_or_none()

    if not att:
        # Primeira vez — criar tentativa com shuffle
        q_r = await db.execute(
            select(QuizQuestion).where(QuizQuestion.quiz_id == sess.quiz_id)
        )
        questions = q_r.scalars().all()
        seed = random.randint(1, 999999)
        q_ids = [str(q.id) for q in questions]
        if sess.shuffle_questions:
            q_ids = _shuffle_with_seed(q_ids, seed)

        att = LiveAttempt(
            session_id=session_id,
            user_id=me.id,
            participant_id=part.id,
            shuffle_seed=seed,
            question_order=q_ids,
        )
        db.add(att)
        await db.commit()
        await db.refresh(att)

    # Verificar expiração do tempo da questão atual
    await _check_and_expire_question(att, db)
    await db.refresh(att)

    total_q = len(att.question_order)

    # Verificar se terminou todas
    if att.current_question_index >= total_q:
        part.status = LiveParticipantStatus.FINISHED
        att.finished_at = _now()
        await db.commit()
        return {"finished": True, "message": "Você completou o quiz!"}

    # Verificar deadline da sessão
    if sess.total_time_seconds and sess.started_at:
        session_deadline = sess.started_at.replace(tzinfo=timezone.utc) + timedelta(seconds=sess.total_time_seconds)
        if _now() >= session_deadline:
            part.status = LiveParticipantStatus.FINISHED
            att.finished_at = _now()
            await db.commit()
            return {"finished": True, "message": "Tempo da sessão esgotado"}

    q_id = uuid.UUID(att.question_order[att.current_question_index])
    q_r = await db.execute(select(QuizQuestion).where(QuizQuestion.id == q_id))
    question = q_r.scalar_one_or_none()
    if not question:
        raise HTTPException(500, "Questão não encontrada")

    # Iniciar timer da questão se não iniciado
    q_seconds = _get_question_seconds(sess, question)
    if not att.question_started_at and q_seconds:
        att.question_started_at = _now()
        deadline = _now() + timedelta(seconds=q_seconds)
        if sess.total_time_seconds and sess.started_at:
            session_deadline = sess.started_at.replace(tzinfo=timezone.utc) + timedelta(seconds=sess.total_time_seconds)
            deadline = min(deadline, session_deadline)
        att.question_deadline_at = deadline
        await db.commit()

    # Opções (embaralhadas se configurado)
    opts_r = await db.execute(select(QuizOption).where(QuizOption.question_id == q_id))
    options = opts_r.scalars().all()
    opt_list = [{"id": str(o.id), "text": o.text} for o in options]
    if sess.shuffle_options:
        opt_list = _shuffle_with_seed(opt_list, att.shuffle_seed + att.current_question_index)

    # Tempo restante da questão
    q_time_remaining = None
    if att.question_deadline_at:
        diff = (att.question_deadline_at.replace(tzinfo=timezone.utc) - _now()).total_seconds()
        q_time_remaining = max(0, int(diff))

    # Tempo restante da sessão
    sess_time_remaining = None
    if sess.total_time_seconds and sess.started_at:
        elapsed = (_now() - sess.started_at.replace(tzinfo=timezone.utc)).total_seconds()
        sess_time_remaining = max(0, int(sess.total_time_seconds - elapsed))

    # Dificuldade só é exibida quando a sessão usa BY_DIFF; fora disso, o campo
    # difficulty da questão é só um default de banco (não configurado para esta sessão)
    q_difficulty = None
    if sess.time_by_difficulty:
        override_diff = (sess.time_by_difficulty.get("overrides") or {}).get(str(question.id))
        q_difficulty = override_diff or question.difficulty or None

    return {
        "finished": False,
        "question_index": att.current_question_index,
        "total_questions": total_q,
        "question_id": str(question.id),
        "statement": question.statement,
        "media_type": question.media_type,
        "media_url": question.media_url,
        "attachment_urls": question.attachment_urls or [],
        "short_reference": question.short_reference,
        "options": opt_list,
        "time_remaining_seconds": q_time_remaining,
        "session_time_remaining_seconds": sess_time_remaining,
        "has_per_question_timer": q_time_remaining is not None or _get_question_seconds(sess, question) is not None,
        "difficulty": q_difficulty,
        "show_difficulty": q_difficulty is not None,
    }


@router.post("/sessions/{session_id}/answer", summary="Responder questão")
async def answer_question(
    session_id: uuid.UUID,
    body: LiveAnswerIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sess = await _get_session_or_404(session_id, db)
    if sess.status != LiveSessionStatus.RUNNING:
        raise HTTPException(400, "Sessão não está ativa")

    part = await _get_participant_or_404(session_id, me.id, db)
    if part.status in (LiveParticipantStatus.KICKED, LiveParticipantStatus.BANNED):
        raise HTTPException(403, f"Você foi {part.status.value.lower()}")
    if part.status == LiveParticipantStatus.PAUSED:
        raise HTTPException(400, "Aguardando reconexão")

    att_r = await db.execute(
        select(LiveAttempt).where(
            LiveAttempt.session_id == session_id,
            LiveAttempt.user_id == me.id,
        )
    )
    att = att_r.scalar_one_or_none()
    if not att:
        raise HTTPException(400, "Tentativa não iniciada. Acesse /question primeiro")

    # Verifica se já respondeu esta questão (idempotência)
    existing_r = await db.execute(
        select(LiveAnswer).where(
            LiveAnswer.attempt_id == att.id,
            LiveAnswer.question_id == body.question_id,
        )
    )
    if existing_r.scalar_one_or_none():
        raise HTTPException(409, "Questão já respondida")

    # Verifica tempo expirado
    if att.question_deadline_at:
        if _now() > att.question_deadline_at.replace(tzinfo=timezone.utc):
            raise HTTPException(400, "Tempo da questão esgotado")

    # Verifica se é a questão atual
    if att.current_question_index >= len(att.question_order):
        raise HTTPException(400, "Quiz já finalizado")
    current_q_id = uuid.UUID(att.question_order[att.current_question_index])
    if current_q_id != body.question_id:
        raise HTTPException(400, "Esta não é a questão atual")

    # Valida opção
    opt_r = await db.execute(
        select(QuizOption).where(QuizOption.id == body.selected_option_id)
    )
    option = opt_r.scalar_one_or_none()
    if not option or str(option.question_id) != str(body.question_id):
        raise HTTPException(400, "Opção inválida")

    # Calcula tempo de resposta
    response_ms = 0
    if att.question_started_at:
        response_ms = int((_now() - att.question_started_at.replace(tzinfo=timezone.utc)).total_seconds() * 1000)

    is_correct = bool(option.is_correct)

    # Registra resposta
    answer = LiveAnswer(
        attempt_id=att.id,
        question_id=body.question_id,
        selected_option_id=body.selected_option_id,
        is_correct=is_correct,
        response_time_ms=response_ms,
        reason=LiveAnswerReason.NORMAL,
    )
    db.add(answer)

    # Atualiza contadores de forma atômica (evita stale read em async SQLAlchemy)
    next_index = att.current_question_index + 1
    next_started_at = None
    next_deadline_at = None

    # Próxima questão: inicia timer baseado em dificuldade ou per_question
    if next_index < len(att.question_order):
        next_q_id = uuid.UUID(att.question_order[next_index])
        next_q_r  = await db.execute(select(QuizQuestion).where(QuizQuestion.id == next_q_id))
        next_q    = next_q_r.scalar_one_or_none()
        next_q_seconds = _get_question_seconds(sess, next_q)
        if next_q_seconds:
            next_started_at = _now()
            deadline = _now() + timedelta(seconds=next_q_seconds)
            if sess.total_time_seconds and sess.started_at:
                session_deadline = sess.started_at.replace(tzinfo=timezone.utc) + timedelta(seconds=sess.total_time_seconds)
                deadline = min(deadline, session_deadline)
            next_deadline_at = deadline
    elif next_index >= len(att.question_order):
        part.status = LiveParticipantStatus.FINISHED
        att.finished_at = _now()

    # UPDATE atômico: usa SQL-level increment para evitar perda de dados
    await db.execute(
        update(LiveAttempt)
        .where(LiveAttempt.id == att.id)
        .values(
            answered_count=LiveAttempt.answered_count + 1,
            correct_count=LiveAttempt.correct_count + (1 if is_correct else 0),
            total_time_ms=LiveAttempt.total_time_ms + response_ms,
            current_question_index=next_index,
            question_started_at=next_started_at,
            question_deadline_at=next_deadline_at,
        )
    )

    await db.commit()
    await db.refresh(att)  # sincroniza o objeto com os valores salvos no DB

    # Buscar gabarito correto para mostrar ao aluno
    correct_opt_r = await db.execute(
        select(QuizOption).where(
            QuizOption.question_id == body.question_id,
            QuizOption.is_correct == True,
        )
    )
    correct_opt = correct_opt_r.scalar_one_or_none()

    # Scoreboard atualizado e rank do aluno
    scoreboard = await _build_scoreboard(session_id, db)
    my_rank = next((e.rank for e in scoreboard.entries if e.user_id == me.id), None)

    # Broadcast para professor
    await manager.broadcast_prof(str(session_id), {
        "type": "ANSWER_RECEIVED",
        "user_id": str(me.id),
        "question_id": str(body.question_id),
        "is_correct": is_correct,
        "response_time_ms": response_ms,
        "scoreboard": scoreboard.dict(),
    })

    return {
        "is_correct": is_correct,
        # só revela a opção correta se show_answer_immediate estiver ativo
        "correct_option_id": str(correct_opt.id) if correct_opt and sess.show_answer_immediate else None,
        "show_answer": sess.show_answer_immediate,
        "show_ranking": sess.show_ranking_students,
        "response_time_ms": response_ms,
        "your_rank": my_rank if sess.show_ranking_students else None,
        "message": "Correto! 🎉" if is_correct else "Incorreto 😕",
    }


@router.get("/sessions/{session_id}/result", summary="Resultado final do aluno")
async def get_student_result(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    att_r = await db.execute(
        select(LiveAttempt).where(
            LiveAttempt.session_id == session_id,
            LiveAttempt.user_id == me.id,
        )
    )
    att = att_r.scalar_one_or_none()
    if not att:
        raise HTTPException(404, "Você não participou desta sessão")

    sess = await _get_session_or_404(session_id, db)
    scoreboard = await _build_scoreboard(session_id, db)
    my_entry = next((e for e in scoreboard.entries if e.user_id == me.id), None)

    # Ranking só é definitivo quando a sessão terminou (todos finalizaram,
    # o professor encerrou, ou o tempo acabou) — antes disso é provisório,
    # pois outros jogadores ainda podem responder e mudar as posições.
    is_final = sess.status == LiveSessionStatus.ENDED
    finished_count = sum(1 for e in scoreboard.entries if e.answered_count >= e.total_questions and e.total_questions > 0)

    return {
        "session_status": sess.status.value,
        "is_final": is_final,
        "finished_count": finished_count,
        "correct_count": att.correct_count,
        "answered_count": att.answered_count,
        "total_questions": len(att.question_order),
        "accuracy_pct": round(att.correct_count / att.answered_count * 100, 1) if att.answered_count > 0 else 0,
        "total_time_ms": att.total_time_ms,
        "avg_time_ms": round(att.total_time_ms / att.answered_count, 1) if att.answered_count > 0 else 0,
        "rank": my_entry.rank if my_entry else None,
        "total_participants": len(scoreboard.entries),
        "answers": [
            {
                "question_id": str(a.question_id),
                "statement": a.question.statement if a.question else "",
                "selected_option_id": str(a.selected_option_id) if a.selected_option_id else None,
                "is_correct": a.is_correct,
                "response_time_ms": a.response_time_ms,
                "reason": a.reason.value,
            }
            for a in sorted(att.answers, key=lambda x: x.answered_at)
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ══════════════════════════════════════════════════════════════════════════════

@router.websocket("/sessions/{session_id}/ws/professor")
async def ws_professor(
    session_id: uuid.UUID,
    websocket: WebSocket,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    """WebSocket para professor receber updates em tempo real.

    O parâmetro "token" existia na assinatura mas nunca era validado —
    qualquer um que soubesse o session_id (um UUID) conseguia conectar
    aqui sem credencial nenhuma e ver em tempo real a pontuação e as
    respostas de todos os alunos da sessão (achado em auditoria de
    segurança). Agora decodifica o token de verdade e confere que é um
    professor (ou admin) dono desta sessão especificamente.
    """
    # Validação ANTES de aceitar a conexão — padrão recomendado do
    # FastAPI pra rejeitar WebSocket sem credencial válida.
    user = await resolve_user_from_token_string(token, db)
    if not user or user.role.value not in ("PROFESSOR", "ADMIN"):
        await websocket.close(code=4401)
        return
    sess_q = await db.execute(select(LiveSession).where(LiveSession.id == session_id))
    session = sess_q.scalar_one_or_none()
    if not session or (user.role.value != "ADMIN" and session.created_by != user.id):
        await websocket.close(code=4403)
        return

    await manager.connect_prof(str(session_id), websocket)
    try:
        while True:
            # Mantém conexão viva + detecta desconexão
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        manager.disconnect_prof(str(session_id), websocket)


@router.websocket("/sessions/{session_id}/ws/student")
async def ws_student(
    session_id: uuid.UUID,
    websocket: WebSocket,
    user_id: str = "",
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    """WebSocket para aluno receber eventos (aprovação, start, end, etc.).

    Antes, "user_id" vinha direto do cliente sem nenhuma verificação —
    qualquer um que soubesse o user_id de outro aluno conseguia se
    conectar se passando por ele, roubando a conexão dele (achado em
    auditoria de segurança). O frontend já manda "token" nessa mesma
    URL desde sempre (LiveWaiting.tsx/LivePlay.tsx), só que o backend
    nunca declarava esse parâmetro nem conferia — agora decodifica o
    token de verdade e usa o ID de dentro dele, ignorando o que o
    cliente alegou ser caso não bata.
    """
    # Validação ANTES de aceitar a conexão — padrão recomendado do
    # FastAPI pra rejeitar WebSocket sem credencial válida.
    user = await resolve_user_from_token_string(token, db)
    if not user or str(user.id) != user_id:
        await websocket.close(code=4401)
        return

    await manager.connect_student(str(session_id), user_id, websocket)
    try:
        while True:
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        manager.disconnect_student(str(session_id), user_id)


# ── Background task: detectar desconexões por timeout de heartbeat ─────────────

async def _disconnect_checker():
    """Roda em background, marca como DISCONNECTED quem não mandou heartbeat há 30s."""
    from app.db.session import AsyncSessionLocal
    while True:
        await asyncio.sleep(15)
        try:
            async with AsyncSessionLocal() as db:
                cutoff = _now() - timedelta(seconds=30)
                r = await db.execute(
                    select(LiveParticipant).where(
                        LiveParticipant.status == LiveParticipantStatus.RUNNING,
                        LiveParticipant.last_seen_at < cutoff,
                    )
                )
                for part in r.scalars().all():
                    part.status = LiveParticipantStatus.DISCONNECTED
                    await manager.broadcast_prof(str(part.session_id), {
                        "type": "PARTICIPANT_DISCONNECTED",
                        "user_id": str(part.user_id),
                    })
                await db.commit()
        except Exception:
            pass

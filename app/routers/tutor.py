"""
Router do Tutor — usa árvore de decisão + LLM com fallback multi-provedor.
A lógica de "o que fazer" está no decision_tree.yaml.
A lógica de "quem responde" está no llm_providers.yaml.
Os prompts estão no tutor_prompts.yaml.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.utils.rbac import get_current_user, get_optional_user
from app.utils.rate_limit import rate_limiter
from app.config import settings
from app.models import User
from app.models.quiz import Quiz, TutorConfig, QuizQuestion, QuizMode
from app.models.attempt import Attempt, AttemptStatus, AttemptQuestionState, Answer
from app.models.audit import TutorInteraction
from app.schemas.tutor import TutorAskRequest, TutorAskResponse
from app.services.audit import event

# Novos módulos de IA
from app.ai.decision_tree.engine import evaluate, build_tutor_context
from app.ai.llm.manager import llm_manager
from app.tutor.service import TutorService
from app.tutor.schemas import TutorContext
from app.tutor.leak_guard import response_leaks_answer, response_looks_like_leaked_reasoning, get_safe_redirect_message
from app.ai.rag.retriever import retrieve as rag_retrieve
from app.ai.llm.prompt_builder import (
    build_tutor_messages,
    get_positive_reinforcement,
    get_encouragement,
    get_message,
)

logger = logging.getLogger(__name__)
tutor_service = TutorService()

router = APIRouter(prefix="/tutor", tags=["tutor"])


async def _get_question_context(qq: QuizQuestion) -> dict:
    """Extrai contexto textual da questão para o LLM."""
    options_lines = []
    for o in sorted(qq.options, key=lambda x: x.order):
        options_lines.append(f"  {o.text}")
    return {
        "question_statement": qq.statement,
        "options_text": "\n".join(options_lines),
        "topic": qq.topic or "",
        "objective": qq.objective or "",
        "explanation": qq.explanation or "",
        "has_explanation": bool(qq.explanation),
        "hint_1": qq.hint_1 or "",
        "hint_2": qq.hint_2 or "",
        "hint_3": qq.hint_3 or "",
    }


async def _count_tutor_interactions(db: AsyncSession, attempt_id) -> int:
    q = await db.execute(
        select(func.count()).where(TutorInteraction.attempt_id == attempt_id)
    )
    return q.scalar() or 0


async def _get_question_state(db: AsyncSession, attempt_id, question_id) -> AttemptQuestionState | None:
    q = await db.execute(
        select(AttemptQuestionState).where(
            AttemptQuestionState.attempt_id == attempt_id,
            AttemptQuestionState.question_id == question_id,
        )
    )
    return q.scalar_one_or_none()


async def _get_answer(db: AsyncSession, attempt_id, question_id) -> Answer | None:
    q = await db.execute(
        select(Answer).where(
            Answer.attempt_id == attempt_id,
            Answer.question_id == question_id,
        )
    )
    return q.scalar_one_or_none()


def _format_message(template: str | None, **kwargs) -> str | None:
    if not template:
        return None
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


@router.post("/ask", response_model=TutorAskResponse)
async def ask_tutor(
    payload: TutorAskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    me: User | None = Depends(get_optional_user),
):
    # --- Rate limiting ---
    ip = request.client.host if request.client else "unknown"
    key = str(me.id) if me else ip
    if not rate_limiter.hit(key, "tutor_ask", settings.RL_TUTOR_PER_MIN):
        raise HTTPException(status_code=429, detail="Muitas solicitações. Aguarde um momento.")

    # --- Carregar tentativa ---
    att_q = await db.execute(select(Attempt).where(Attempt.id == payload.attempt_id))
    attempt = att_q.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Tentativa não está em andamento")

    # --- Carregar quiz ---
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == attempt.quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Questionário não encontrado")

    # --- Carregar tutor config ---
    tc: TutorConfig | None = quiz.tutor_config
    if not tc or not tc.enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "O tutor de IA não está ativado para este questionário. "
                "Fale com seu professor para ativar essa função nas "
                "configurações do questionário."
            ),
        )

    # --- Carregar questão atual ---
    qq: QuizQuestion | None = None
    q_ctx: dict = {}
    state: AttemptQuestionState | None = None
    answer: Answer | None = None

    if payload.question_id:
        qq_q = await db.execute(select(QuizQuestion).where(QuizQuestion.id == payload.question_id))
        qq = qq_q.scalar_one_or_none()
        if qq:
            q_ctx = await _get_question_context(qq)
            state = await _get_question_state(db, attempt.id, qq.id)
            answer = await _get_answer(db, attempt.id, qq.id)

    # --- Verificar scope ---
    # Antes, um detector por sobreposição de palavras bloqueava a mensagem
    # ANTES de chegar na IA — mas ele só sabe comparar palavras, não
    # sentido, e bloqueava até pedidos legítimos ("me ajude", "dê uma
    # dica") só por não repetirem palavras do enunciado. O prompt da IA
    # (tutor_prompts.yaml) já instrui ela a redirecionar perguntas
    # realmente fora do assunto — e ela entende sentido, não só palavras —
    # então confiamos nisso em vez de um filtro raso antes da IA.
    fora_escopo = False

    # --- Montar contexto para árvore de decisão ---
    hints_usados = state.hints_used if state else 0
    acertou = answer.is_correct if answer else None
    interacoes_total = await _count_tutor_interactions(db, attempt.id)

    tree_ctx = build_tutor_context(
        tentativas_usadas=state.hints_used if state else 0,  # reaproveitado como counter
        max_tentativas=quiz.max_attempts,
        dicas_usadas=hints_usados,
        max_dicas=quiz.hint_levels,
        acertou=acertou,
        modo_questionario=quiz.mode.value,
        escopo_tutor=tc.scope.value,
        fora_escopo=fora_escopo,
        tem_explicacao=q_ctx.get("has_explanation", False),
        nivel_dificuldade=qq.difficulty if qq else None,
        interacoes_tutor_total=interacoes_total,
    )

    # --- Executar árvore de decisão ---
    decision = evaluate(tree_ctx)
    logger.info(f"Tutor decision: {decision.action} for attempt={attempt.id}")

    # --- Processar ação ---
    response_content = ""
    out_of_scope = fora_escopo

    if decision.action == "BLOCK_OUT_OF_SCOPE":
        response_content = get_message("out_of_scope", scope_description=tc.scope.value)
        if not response_content:
            response_content = decision.message_template or "Sua pergunta está fora do escopo."
        out_of_scope = True

    elif decision.action == "SEND_RESTRICTED_HELP":
        response_content = get_message("evaluation_restricted") or decision.message_template or "Durante avaliação, não posso ajudar."

    elif decision.action == "SEND_POSITIVE_REINFORCEMENT":
        base = get_positive_reinforcement()
        explanation = q_ctx.get("explanation", "")
        response_content = base
        if explanation and tc.allow_explanation:
            response_content += f"\n\n{explanation}"

    elif decision.action == "SEND_FULL_EXPLANATION":
        explanation = q_ctx.get("explanation", "")
        response_content = (
            f"Você usou todas as tentativas. Aqui está a explicação completa:\n\n{explanation}"
            if explanation else "Você usou todas as tentativas. Consulte o material de apoio."
        )

    elif decision.action == "OFFER_HINT":
        next_level = hints_usados + 1
        hint_map = {1: q_ctx.get("hint_1"), 2: q_ctx.get("hint_2"), 3: q_ctx.get("hint_3")}
        hint_text = hint_map.get(next_level, "")
        if hint_text:
            response_content = f"💡 **Dica (nível {next_level}):** {hint_text}"
            # Atualizar state
            if state:
                state.hints_used = next_level
        else:
            response_content = get_message("max_hints_reached") or "Não há mais dicas disponíveis."

    elif decision.action == "FEEDBACK_CORRECT":
        response_content = _format_message(
            decision.message_template,
            explicacao_questao=q_ctx.get("explanation", "") if decision.show_explanation else "",
        ) or get_positive_reinforcement()

    elif decision.action in ("FEEDBACK_WRONG_FINAL", "FEEDBACK_WRONG_RETRY"):
        response_content = _format_message(
            decision.message_template,
            explicacao_questao=q_ctx.get("explanation", "") if decision.show_explanation else "",
        ) or get_encouragement(q_ctx.get("topic", ""))

    elif decision.action == "FEEDBACK_EVALUATION_MODE":
        response_content = decision.message_template or "Resposta registrada."

    elif decision.action == "SEND_TO_LLM":
        # ===== Motor escolhido pelo .env =====
        # TUTOR_ENGINE=API_DIRECT | DECISION_TREE | RAG_LLM

        # Forçar liberação após N trocas — calculado em código porque o
        # modelo não conta repetições/trocas de forma confiável só com a
        # instrução no prompt (testado e confirmado: ele demora várias
        # trocas a mais do que devia pra "perceber" que já pode liberar).
        user_turns = sum(1 for h in payload.history if h.role == "user")
        forced_hint = ""
        if user_turns >= 3:
            forced_hint = (
                "Essa conversa já teve várias trocas sobre a mesma questão. "
                "Se o aluno demonstrou QUALQUER confiança numa alternativa "
                "(mesmo só repetindo a mesma sem justificativa nova), NÃO "
                "peça mais explicação nem faça outra pergunta socrática "
                "aberta — confirme e incentive-o diretamente a marcar a "
                "resposta agora."
            )

        ctx = TutorContext(
            attempt_id=str(attempt.id),
            quiz_id=str(quiz.id),
            question_id=str(qq.id),
            scope=tc.scope.value,
            quiz_title=quiz.title,
            question_statement=q_ctx.get("question_statement", ""),
            options_text=q_ctx.get("options_text", ""),
            topic=q_ctx.get("topic", ""),
            objective=q_ctx.get("objective", ""),
            explanation=q_ctx.get("explanation", ""),
            hints_used=hints_usados,
            # Só o primeiro nome — nome completo soa formal demais numa
            # conversa de chat, e é o que a IA usa pra personalizar
            # toda a conversa, não só a saudação inicial.
            student_name=((me.name or "").strip().split(" ")[0] if me else ""),
            history=[h.model_dump() for h in payload.history],
            system_hint=forced_hint,
        )

        is_attempt_active = attempt.status == AttemptStatus.IN_PROGRESS
        is_quiz_open = quiz.status != "CLOSED"
        evaluation_mode = (quiz.mode == QuizMode.AVALIACAO)

        result = await tutor_service.answer(
            db=db,
            context=ctx,
            user_message=payload.message,
            is_attempt_active=is_attempt_active,
            is_quiz_open=is_quiz_open,
            out_of_scope=out_of_scope,
            evaluation_mode=evaluation_mode,
        )
        response_content = result.message

        # Rede de segurança: a instrução no prompt pra nunca revelar a
        # resposta é só instrução, a IA já vazou de verdade em testes ao
        # vivo (inclusive escalando demais em pedidos repetidos de dica).
        # Essa checagem roda em código, comparando com o texto literal da
        # alternativa correta — que nunca foi mandado pra IA — então não
        # depende dela seguir regra nenhuma.
        correct_texts = [o.text for o in qq.options if o.is_correct]
        if response_leaks_answer(response_content, correct_texts):
            logger.warning(f"[TutorGuard] Resposta bloqueada por vazar a alternativa correta — question_id={qq.id}")
            response_content = get_safe_redirect_message()
        elif response_looks_like_leaked_reasoning(response_content):
            # Raciocínio interno do modelo vazando em inglês, sem tag
            # nenhuma pra identificar (a limpeza de <think> em
            # openai_compat.py não pega isso) — mesma gravidade do caso
            # acima, bloqueado do mesmo jeito.
            logger.warning(f"[TutorGuard] Resposta bloqueada por parecer raciocínio interno vazando — question_id={qq.id}")
            response_content = get_safe_redirect_message()

    else:
        response_content = decision.message_template or "Como posso ajudá-lo com esta questão?"

    # --- Registrar interação ---
    if decision.log_interaction:
        db.add(TutorInteraction(
            attempt_id=attempt.id,
            question_id=payload.question_id,
            user_id=me.id if me else None,
            kind=decision.log_kind,
            user_message=payload.message,
            tutor_message=response_content[:4000],
            out_of_scope="true" if out_of_scope else "false",
            meta={"action": decision.action, "scope": tc.scope.value},
        ))
    await event(db, str(me.id) if me else None, "TUTOR_ASKED", {
        "attempt_id": str(attempt.id),
        "action": decision.action,
        "out_of_scope": out_of_scope,
    })
    await db.commit()

    return TutorAskResponse(message=response_content, out_of_scope=out_of_scope)


@router.get("/providers/status")
async def providers_status(me: User = Depends(get_current_user)):
    """Lista os provedores de LLM ativos (admin/professor)."""
    from app.models.user import UserRole
    if me.role not in (UserRole.ADMIN, UserRole.PROFESSOR):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"providers": llm_manager.list_providers()}


from app.ai.configs.loader import reload_all

@router.post("/providers/reload")
async def reload_providers(me: User = Depends(get_current_user)):
    """Recarrega configurações de LLM e árvore de decisão (sem reiniciar)."""
    from app.models.user import UserRole
    if me.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Apenas admins podem recarregar configurações")
    reload_all()
    llm_manager.reload()
    return {"message": "Configurações recarregadas com sucesso"}

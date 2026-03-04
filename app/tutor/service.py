"""TutorService: regras iguais + motor escolhido + retorno padrão"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from app.tutor.schemas import TutorContext, TutorEngineResult
from app.tutor.dispatcher import get_engine
from app.tutor.rules.guardrails import evaluate_guardrails


class TutorService:
    async def answer(
        self,
        *,
        db: AsyncSession,
        context: TutorContext,
        user_message: str,
        is_attempt_active: bool,
        is_quiz_open: bool,
        out_of_scope: bool,
        evaluation_mode: bool,
    ) -> TutorEngineResult:
        decision = evaluate_guardrails(
            is_attempt_active=is_attempt_active,
            is_quiz_open=is_quiz_open,
            out_of_scope=out_of_scope,
            evaluation_mode=evaluation_mode,
        )
        if not decision.allowed:
            return TutorEngineResult(decision.user_message, "DECISION_TREE", {"blocked": True, "reason": decision.reason})

        engine = get_engine()
        result = await engine.generate(context=context, user_message=user_message)

        if result.message and len(result.message) > 1200:
            result.message = result.message[:1200] + "..."
        return result

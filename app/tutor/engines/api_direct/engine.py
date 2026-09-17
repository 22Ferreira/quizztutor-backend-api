"""Motor API_DIRECT

Use agora: Gemini via API.
Escolha no .env:
- TUTOR_ENGINE=API_DIRECT
- AI_PROVIDER=gemini
"""

from __future__ import annotations

from app.ai.llm.manager import llm_manager
from app.ai.llm.prompt_builder import build_tutor_messages
from app.tutor.engines.base import TutorEngine
from app.tutor.schemas import TutorContext, TutorEngineResult


class ApiDirectEngine(TutorEngine):
    async def generate(self, *, context: TutorContext, user_message: str) -> TutorEngineResult:
        messages = build_tutor_messages(
            user_message=user_message,
            scope=context.scope,
            quiz_title=context.quiz_title,
            question_statement=context.question_statement,
            options_text=context.options_text,
            topic=context.topic,
            objective=context.objective,
            explanation=context.explanation,
            custom_system_prompt=None,
            include_explanation=False,
            system_hint=None,
            student_name=context.student_name,
            history=context.history,
        )

        llm = await llm_manager.chat(messages)
        if not llm.success:
            return TutorEngineResult("Não consegui acessar o tutor de IA agora. Tente novamente em instantes.", "API_DIRECT", {"error": llm.error})
        return TutorEngineResult(llm.content, "API_DIRECT")

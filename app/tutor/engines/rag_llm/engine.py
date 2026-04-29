"""Motor RAG_LLM

Hoje: funciona igual API_DIRECT (retriever retorna vazio).
Amanhã: implemente retrieve_context() e ele vira RAG de verdade.
"""

from __future__ import annotations

from app.ai.llm.manager import llm_manager
from app.ai.llm.prompt_builder import build_tutor_messages
from app.tutor.engines.base import TutorEngine
from app.tutor.schemas import TutorContext, TutorEngineResult
from app.tutor.engines.rag_llm.retriever import retrieve_context


class RagLlmEngine(TutorEngine):
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
        )

        ctx = retrieve_context(user_message)
        if ctx:
            messages.insert(1, {"role": "system", "content": "CONTEÚDO DE APOIO (RAG):\n\n" + ctx})

        llm = await llm_manager.chat(messages)
        if not llm.success:
            return TutorEngineResult("Não consegui acessar o tutor de IA agora. Tente novamente em instantes.", "RAG_LLM", {"error": llm.error})
        return TutorEngineResult(llm.content, "RAG_LLM", {"rag_used": bool(ctx)})

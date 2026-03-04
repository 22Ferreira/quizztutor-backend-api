"""Motor DECISION_TREE (sem LLM) — ESQUELETO

Como criar sua árvore depois (bem simples):
1) Crie um YAML com regras:
   - se hints_remaining -> give_hint
   - senão -> ask_socratic
2) No método generate(), carregue esse YAML e execute.

Por enquanto, este motor só demonstra o comportamento:
- libera a próxima dica (nível 1..3)
- se acabar, faz pergunta socrática
"""

from __future__ import annotations

from app.tutor.engines.base import TutorEngine
from app.tutor.schemas import TutorContext, TutorEngineResult


class DecisionTreeEngine(TutorEngine):
    async def generate(self, *, context: TutorContext, user_message: str) -> TutorEngineResult:
        next_level = context.hints_used + 1
        if next_level <= 3:
            msg = f"💡 **Dica (nível {next_level}):** identifique no enunciado o que pode ser executado em paralelo."
        else:
            msg = "Vamos por partes: qual alternativa você acha mais provável e por quê?"
        return TutorEngineResult(msg, "DECISION_TREE", {"hint_level": next_level})

"""app.tutor.schemas

Este arquivo define os "contratos" internos do tutor.

A ideia é simples:
- A rota /tutor/ask NÃO conversa com Gemini/RAG/Árvore diretamente.
- Ela chama o TutorService.
- O TutorService escolhe um "motor" (engine) e recebe um resultado PADRÃO.

Assim, o resto do sistema (logs, auditoria, analytics) fica igual,
independente do motor escolhido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any


TutorEngineName = Literal["API_DIRECT", "DECISION_TREE", "RAG_LLM"]


@dataclass
class TutorContext:
    """Contexto mínimo para o tutor responder.

    Você pode adicionar mais campos depois sem quebrar tudo.
    """
    attempt_id: str
    quiz_id: str
    question_id: str
    scope: str
    quiz_title: str
    question_statement: str
    options_text: str
    topic: str
    objective: str
    explanation: str
    hints_used: int
    student_name: str = ""
    # Últimas trocas da conversa, mais antiga primeiro: [{"role": "user"|"assistant", "content": "..."}]
    history: list[Dict[str, str]] = field(default_factory=list)
    # Instrução extra calculada em código (não pelo LLM) pra garantir
    # comportamento que o modelo não segue de forma confiável só com o
    # prompt geral — ex: forçar liberar o aluno pra responder depois de
    # N trocas, já que contar repetições "de cabeça" o modelo faz mal.
    system_hint: str = ""


@dataclass
class TutorEngineResult:
    """Resultado PADRÃO de qualquer motor."""
    message: str
    engine: TutorEngineName
    meta: Optional[Dict[str, Any]] = None

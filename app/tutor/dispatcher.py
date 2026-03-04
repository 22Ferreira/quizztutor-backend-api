"""Escolha do motor do tutor (um lugar só)

Trocar motor:
- backend/.env -> TUTOR_ENGINE=API_DIRECT | DECISION_TREE | RAG_LLM

Você disse que quer usar apenas 1 modelo por vez:
- backend/.env -> AI_PROVIDER=gemini (exemplo)
"""

from __future__ import annotations

from app.config import settings
from app.tutor.engines.api_direct.engine import ApiDirectEngine
from app.tutor.engines.decision_tree.engine import DecisionTreeEngine
from app.tutor.engines.rag_llm.engine import RagLlmEngine
from app.tutor.engines.base import TutorEngine

_api = ApiDirectEngine()
_tree = DecisionTreeEngine()
_rag = RagLlmEngine()

def get_engine() -> TutorEngine:
    name = (settings.TUTOR_ENGINE or "API_DIRECT").upper()
    if name == "DECISION_TREE":
        return _tree
    if name == "RAG_LLM":
        return _rag
    return _api

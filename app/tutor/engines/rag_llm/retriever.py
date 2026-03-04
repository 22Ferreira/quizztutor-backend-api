"""RAG — ESQUELETO (didático)

RAG real (quando você implementar):
- Indexar materiais -> embeddings -> banco vetorial (ex: Postgres + pgvector)
- Recuperar top-k trechos a cada pergunta
- Injetar no prompt do LLM

Por enquanto, retorne "" para funcionar igual ao API_DIRECT.
"""

from __future__ import annotations


def retrieve_context(query: str) -> str:
    return ""

"""
RAG retriever com cache em memória.
Na primeira chamada indexa os arquivos do corpus; chamadas seguintes
usam o índice cacheado, evitando I/O e tokenização a cada request.
"""
import logging
import re
import threading
from pathlib import Path
from typing import List, Tuple, Dict

from app.config import settings

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[\wÀ-ÿ]{3,}", re.UNICODE)

# Cache: {corpus_dir: [(tokens, filename, text_snippet)]}
_INDEX_CACHE: Dict[str, List[Tuple[set, str, str]]] = {}
_INDEX_LOCK = threading.Lock()


def _tokenize(s: str) -> set:
    return {m.group(0).lower() for m in _WORD.finditer(s or "")}


def _build_index(base: Path) -> List[Tuple[set, str, str]]:
    """Lê todos os arquivos e constrói índice de tokens. Roda uma vez."""
    index = []
    for ext in ("*.md", "*.txt"):
        for fp in base.rglob(ext):
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
                tokens = _tokenize(text[:20000])
                if tokens:
                    index.append((tokens, fp.name, text))
            except Exception as e:
                logger.warning(f"[RAG] Erro ao ler {fp}: {e}")
    logger.info(f"[RAG] Índice construído com {len(index)} arquivos de {base}")
    return index


def _get_index(corpus_dir: str) -> List[Tuple[set, str, str]]:
    """Retorna índice cacheado ou constrói se necessário."""
    if corpus_dir not in _INDEX_CACHE:
        with _INDEX_LOCK:
            if corpus_dir not in _INDEX_CACHE:  # double-check
                base = Path(corpus_dir)
                _INDEX_CACHE[corpus_dir] = _build_index(base) if base.exists() else []
    return _INDEX_CACHE[corpus_dir]


def retrieve(query: str) -> str:
    """
    Busca por sobreposição de tokens no corpus cacheado.
    Retorna string com até settings.RAG_MAX_CHARS, composta de chunks relevantes.
    """
    corpus_dir = settings.RAG_CORPUS_DIR.strip()
    if not corpus_dir:
        return ""

    qtok = _tokenize(query)
    if not qtok:
        return ""

    index = _get_index(corpus_dir)
    if not index:
        return ""

    # Pontuar por sobreposição
    scored: List[Tuple[int, str, str]] = []
    for tokens, filename, text in index:
        score = len(qtok & tokens)
        if score > 0:
            scored.append((score, filename, text))

    scored.sort(key=lambda x: x[0], reverse=True)

    chunks: List[str] = []
    total_chars = 0
    for score, filename, text in scored[:max(1, settings.RAG_MAX_CHUNKS)]:
        snippet = text.strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "..."
        block = f"Fonte: {filename}\n{snippet}"
        if total_chars + len(block) > settings.RAG_MAX_CHARS:
            break
        chunks.append(block)
        total_chars += len(block)

    return "\n\n---\n\n".join(chunks)


def invalidate_cache():
    """Limpa o cache (útil ao atualizar corpus em runtime)."""
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()
    logger.info("[RAG] Cache invalidado")

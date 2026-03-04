import os
import re
from pathlib import Path
from typing import List, Tuple

from app.config import settings

_WORD = re.compile(r"[\wÀ-ÿ]{3,}", re.UNICODE)

def _tokenize(s: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD.finditer(s or "")}

def _iter_files(base: Path) -> List[Path]:
    if not base.exists():
        return []
    files: List[Path] = []
    for ext in ("*.md", "*.txt"):
        files.extend(base.rglob(ext))
    return files

def retrieve(query: str) -> str:
    """RAG simples (baseline): busca por sobreposição de palavras em arquivos .md/.txt.
    Retorna um texto com até settings.RAG_MAX_CHARS, composto de até settings.RAG_MAX_CHUNKS trechos.
    Se RAG_CORPUS_DIR estiver vazio/inexistente, retorna string vazia.
    """
    corpus_dir = settings.RAG_CORPUS_DIR.strip()
    if not corpus_dir:
        return ""
    base = Path(corpus_dir)
    if not base.exists():
        return ""

    qtok = _tokenize(query)
    if not qtok:
        return ""

    scored: List[Tuple[int, Path, str]] = []
    for fp in _iter_files(base):
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # score by token overlap
        stok = _tokenize(text[:20000])  # cap for speed
        score = len(qtok & stok)
        if score <= 0:
            continue
        scored.append((score, fp, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    chunks: List[str] = []
    total_chars = 0
    for score, fp, text in scored[: max(1, settings.RAG_MAX_CHUNKS)]:
        snippet = text.strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "..."
        block = f"Fonte: {fp.name}\n{snippet}"
        if total_chars + len(block) > settings.RAG_MAX_CHARS:
            break
        chunks.append(block)
        total_chars += len(block)

    if not chunks:
        return ""
    return "\n\n---\n\n".join(chunks)

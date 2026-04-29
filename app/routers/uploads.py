"""
Router de upload de arquivos.

Armazenamento:
  - Local (desenvolvimento): salva em uploads/<kind>/
  - MinIO (produção):        basta trocar o _save_file() abaixo
  
Endpoint fixo: POST /uploads/{kind}
  kind ∈ image | audio | video | attachment

Retorna: { "url": "..." }
"""

import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from app.utils.rbac import require_roles

router = APIRouter(prefix="/uploads", tags=["uploads"])

# ── Configuração ─────────────────────────────────────────────────────────────

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", "uploads"))

ALLOWED: dict[str, tuple[set[str], int]] = {
    #  kind         extensões              limite (bytes)
    "image":      ({"png", "jpg", "jpeg", "webp"},   5  * 1024 * 1024),
    "audio":      ({"mp3", "wav", "ogg"},             25 * 1024 * 1024),
    "video":      ({"mp4", "webm"},                   250 * 1024 * 1024),
    "attachment": ({"pdf"},                            20 * 1024 * 1024),
}

KindType = Literal["image", "audio", "video", "attachment"]


def _ensure_dir(kind: str) -> Path:
    d = UPLOAD_ROOT / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def _save_file(kind: str, file: UploadFile) -> str:
    """
    Salva o arquivo localmente e retorna a URL relativa.
    Para MinIO: substitua este método por upload ao bucket.
    """
    ext = _ext(file.filename or "")
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    dest = _ensure_dir(kind) / safe_name

    content = await file.read()
    dest.write_bytes(content)

    # URL relativa — o frontend prefixará com a base URL da API
    return f"/uploads/{kind}/{safe_name}"


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post(
    "/{kind}",
    dependencies=[Depends(require_roles("PROFESSOR", "ADMIN"))],
    summary="Upload de mídia ou anexo para enunciado de questão",
)
async def upload_file(
    kind: KindType,
    file: UploadFile = File(...),
):
    if kind not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Tipo inválido: {kind}")

    allowed_exts, max_bytes = ALLOWED[kind]
    ext = _ext(file.filename or "")

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=415,
            detail=f"Extensão .{ext} não permitida para '{kind}'. Permitidas: {', '.join(sorted(allowed_exts))}",
        )

    # Verificar tamanho sem ler tudo de uma vez
    content = await file.read()
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande. Limite para '{kind}': {limit_mb} MB",
        )

    # Rewind para o _save_file
    await file.seek(0)
    url = await _save_file(kind, file)

    return {"url": url}

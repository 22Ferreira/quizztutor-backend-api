import asyncio
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from app.config import settings
from app.db.init_db import init_db
from app.db.session import AsyncSessionLocal
from app.routers import (
    auth, classes, quizzes, attempts, tutor,
    chat, analytics, admin, global_quizzes, admin_global_quizzes,
)
from app.routers.uploads import router as uploads_router, UPLOAD_ROOT
from app.routers.live import router as live_router, _disconnect_checker

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend completo para plataforma de questionários com tutor IA e RBAC.",
    version="1.0.0",
    docs_url="/docs" if settings.ENV != "prod" else None,
    redoc_url="/redoc" if settings.ENV != "prod" else None,
)


# ── 1. GZip — comprime respostas > 1KB (reduz 60–80% em JSON grandes) ────────
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── 2. CORS via env ───────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 3. Limite de tamanho de body (evita payloads maliciosos) ─────────────────
class LimitBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = 2 * 1024 * 1024):  # 2 MB
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # Upload endpoint tem seus próprios limites por tipo de arquivo
        if request.url.path.startswith("/uploads/"):
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Payload muito grande (máx 2MB)"}, status_code=413)
        return await call_next(request)


app.add_middleware(LimitBodySizeMiddleware, max_bytes=2_097_152)


# ── 4. Timeout global (evita requests travados esgotarem o pool) ─────────────
class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout: int = 60):
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            return JSONResponse({"detail": "Request timeout"}, status_code=504)


app.add_middleware(TimeoutMiddleware, timeout=60)


# ── 5. Security headers ───────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    await init_db()
    if settings.ENV == "dev":
        from app.db.seed import seed_mock_data
        await seed_mock_data()
    await _load_secrets_into_env()
    # Background task: detectar alunos desconectados por timeout de heartbeat
    asyncio.create_task(_disconnect_checker())


async def _load_secrets_into_env():
    """
    Copia as chaves de API salvas pelo admin (banco, cifradas) para
    os.environ — assim o código dos provedores de IA (que só sabe ler
    variável de ambiente, sem tocar em nada dele) já enxerga a chave
    certa sem precisar reiniciar o servidor depois de salvar pela tela.
    """
    import os
    from sqlalchemy import select
    from app.models.system_secret import SystemSecret
    from app.utils.secrets_crypto import decrypt_secret

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SystemSecret))).scalars().all()
        for row in rows:
            plain = decrypt_secret(row.encrypted_value)
            if plain:
                os.environ[row.key_name] = plain


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(quizzes.router)
app.include_router(attempts.router)
app.include_router(tutor.router)
app.include_router(chat.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(global_quizzes.router)
app.include_router(admin_global_quizzes.router)
app.include_router(uploads_router)
app.include_router(live_router)

# ── Servir uploads locais como arquivos estáticos ─────────────────────────────
# Em produção com MinIO, este bloco pode ser removido — a URL aponta para o bucket.
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")


# ── Health check real (verifica DB + Redis) ───────────────────────────────────
@app.get("/health")
async def health():
    checks: dict = {"app": True, "db": False, "redis": False}

    # Checar banco
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:
        pass

    # Checar Redis
    try:
        if settings.REDIS_URL:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = True
        else:
            checks["redis"] = None  # não configurado
    except Exception:
        pass

    ok = checks["db"] is True  # mínimo: banco tem que responder
    return JSONResponse(
        {"ok": ok, "env": settings.ENV, "checks": checks},
        status_code=200 if ok else 503,
    )

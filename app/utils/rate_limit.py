"""
Rate limiter com suporte a Redis (produção, multi-worker) e fallback
para memória (dev/sem Redis). Troca automática baseada em REDIS_URL.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from time import time
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Fallback: memória (dev / single-worker)
# ──────────────────────────────────────────────
@dataclass
class _Bucket:
    reset_at: float
    count: int


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: Dict[Tuple[str, str], _Bucket] = {}

    # async só pra manter a mesma interface do RedisRateLimiter (quem
    # chama sempre dá "await", não precisa saber qual dos dois está
    # rodando por trás) — não tem I/O de verdade aqui, então não
    # bloqueia nada.
    async def hit(self, key: str, action: str, limit: int, window_seconds: int = 60) -> bool:
        now = time()
        k = (key, action)
        b = self._buckets.get(k)
        if not b or now >= b.reset_at:
            self._buckets[k] = _Bucket(reset_at=now + window_seconds, count=1)
            return True
        if b.count >= limit:
            return False
        b.count += 1
        return True


# ──────────────────────────────────────────────
# Redis: INCR + EXPIRE (funciona com N workers)
# ──────────────────────────────────────────────
class RedisRateLimiter:
    def __init__(self, redis_url: str):
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def hit(self, key: str, action: str, limit: int, window_seconds: int = 60) -> bool:
        # Antes disso, cada chamada criava uma THREAD nova com um EVENT
        # LOOP novo (via asyncio.run) só pra "fingir" ser síncrono — mas
        # o cliente Redis (self._redis) é um único objeto assíncrono
        # compartilhado, e conexão/socket assíncrono não sobrevive a
        # trocar de loop. Resultado: "Event loop is closed" em toda
        # chamada, sempre caindo no fail-open (return True) do except
        # abaixo — ou seja, o rate limit nunca esteve funcionando de
        # verdade em produção. Agora que os 3 pontos que chamam isso
        # (tutor, início de tentativa, login) já rodam dentro de uma
        # rota async do FastAPI, dá pra usar o MESMO loop com um await
        # direto — sem criar loop novo, sem gambiarra de thread.
        rkey = f"rl:{action}:{key}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, window_seconds)
            results = await pipe.execute()
            count = results[0]
            return count <= limit
        except Exception as e:
            logger.warning(f"[RateLimit] Redis erro: {e}")
            return True  # fail-open: não bloquear por falha do Redis


# ──────────────────────────────────────────────
# Instância global
# ──────────────────────────────────────────────
def _build_limiter():
    from app.config import settings
    if settings.REDIS_URL:
        try:
            limiter = RedisRateLimiter(settings.REDIS_URL)
            logger.info("[RateLimit] Usando Redis: %s", settings.REDIS_URL)
            return limiter
        except Exception as e:
            logger.warning(f"[RateLimit] Falha ao conectar Redis, usando memória: {e}")
    logger.info("[RateLimit] Usando InMemory (dev)")
    return InMemoryRateLimiter()


rate_limiter = _build_limiter()

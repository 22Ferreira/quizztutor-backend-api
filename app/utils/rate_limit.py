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

    def hit(self, key: str, action: str, limit: int, window_seconds: int = 60) -> bool:
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

    def hit(self, key: str, action: str, limit: int, window_seconds: int = 60) -> bool:
        """
        Síncrono por compatibilidade com o código existente.
        Usa run_until_complete internamente para não quebrar a interface.
        Em produção real, prefira chamar hit_async diretamente.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # no contexto async (FastAPI) — criar task segura
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._async_hit(key, action, limit, window_seconds))
                    return future.result(timeout=1)
            else:
                return loop.run_until_complete(self._async_hit(key, action, limit, window_seconds))
        except Exception as e:
            logger.warning(f"[RateLimit] Redis falhou, liberando request: {e}")
            return True  # fail-open: não bloquear por falha do Redis

    async def _async_hit(self, key: str, action: str, limit: int, window_seconds: int) -> bool:
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
            return True  # fail-open


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

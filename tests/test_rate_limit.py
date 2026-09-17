"""Testes do rate limiter (app/utils/rate_limit.py).

InMemoryRateLimiter é testado diretamente aqui (sem infra externa).
RedisRateLimiter não é coberto por teste automatizado — exigiria um
Redis de verdade rodando; mas o bug real que ele tinha (recriar um
event loop novo a cada chamada via asyncio.run, quebrando o cliente
Redis assíncrono compartilhado — sempre caía em "Event loop is closed"
e fail-open, visto ao vivo em produção nos logs) foi corrigido tornando
hit() nativamente async, sem essa gambiarra — quem chama já está
sempre dentro de uma rota async do FastAPI.
"""
import pytest

from app.utils.rate_limit import InMemoryRateLimiter


@pytest.mark.asyncio
async def test_libera_ate_o_limite():
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        assert await limiter.hit("user1", "acao", limit=5, window_seconds=60) is True


@pytest.mark.asyncio
async def test_bloqueia_apos_o_limite():
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        await limiter.hit("user1", "acao", limit=5, window_seconds=60)
    assert await limiter.hit("user1", "acao", limit=5, window_seconds=60) is False


@pytest.mark.asyncio
async def test_chaves_diferentes_nao_interferem_entre_si():
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        await limiter.hit("user1", "acao", limit=5, window_seconds=60)
    # user1 esgotou o limite, mas user2 é independente.
    assert await limiter.hit("user2", "acao", limit=5, window_seconds=60) is True


@pytest.mark.asyncio
async def test_acoes_diferentes_para_mesma_chave_nao_interferem():
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        await limiter.hit("user1", "tutor_ask", limit=5, window_seconds=60)
    # Mesmo usuário, ação diferente (ex: login) — contador separado.
    assert await limiter.hit("user1", "login", limit=5, window_seconds=60) is True


@pytest.mark.asyncio
async def test_janela_expira_e_libera_de_novo():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.hit("user1", "acao", limit=3, window_seconds=0)
    # window_seconds=0: a janela já expirou imediatamente na próxima chamada.
    assert await limiter.hit("user1", "acao", limit=3, window_seconds=0) is True

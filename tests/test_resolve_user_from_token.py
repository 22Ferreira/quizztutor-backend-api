"""Testes de app.utils.rbac.resolve_user_from_token_string() — usado
pra validar de verdade os WebSockets de sessão ao vivo (achado em
auditoria de segurança: ws_professor aceitava qualquer conexão sem
checar o token, ws_student confiava cegamente no user_id mandado pelo
cliente sem verificar contra nada)."""
import pytest

from app.utils.rbac import resolve_user_from_token_string


@pytest.mark.asyncio
async def test_token_vazio_retorna_none():
    assert await resolve_user_from_token_string("", db=None) is None


@pytest.mark.asyncio
async def test_token_none_retorna_none():
    assert await resolve_user_from_token_string(None, db=None) is None


@pytest.mark.asyncio
async def test_token_invalido_retorna_none():
    # Não é um JWT válido nenhum — decode_token deve levantar ValueError,
    # capturado internamente, retornando None em vez de propagar exceção
    # (importante: um WebSocket não deveria derrubar o servidor por causa
    # de um token forjado/malformado).
    assert await resolve_user_from_token_string("token-forjado-qualquer", db=None) is None

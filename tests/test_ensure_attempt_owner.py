"""Testes de app.utils.rbac.ensure_attempt_owner() — a checagem de
dono da tentativa (achado em auditoria de segurança: rotas de
attempts/tutor/chat carregavam a Attempt só pelo ID da URL, sem checar
se pertencia a quem estava chamando)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.utils.rbac import ensure_attempt_owner


def _user(user_id: str):
    return SimpleNamespace(id=user_id)


def _attempt(participant_user_id: str | None):
    return SimpleNamespace(participant_user_id=participant_user_id)


class TestEnsureAttemptOwner:
    def test_dono_acessando_a_propria_tentativa_passa(self):
        ensure_attempt_owner(_attempt("user-1"), _user("user-1"))  # não deve lançar

    def test_outro_usuario_logado_e_bloqueado(self):
        with pytest.raises(HTTPException) as exc:
            ensure_attempt_owner(_attempt("user-1"), _user("user-2"))
        assert exc.value.status_code == 403

    def test_anonimo_tentando_acessar_tentativa_de_usuario_logado_e_bloqueado(self):
        with pytest.raises(HTTPException) as exc:
            ensure_attempt_owner(_attempt("user-1"), None)
        assert exc.value.status_code == 403

    def test_tentativa_de_convidado_nao_tem_dono_para_checar(self):
        # participant_user_id None = fluxo de convidado (link público/e-mail
        # sem login) — o próprio ID da tentativa já é a credencial, igual
        # sempre funcionou. Não deve bloquear ninguém.
        ensure_attempt_owner(_attempt(None), None)
        ensure_attempt_owner(_attempt(None), _user("qualquer-um"))

    def test_attempt_none_e_tratado_como_nao_encontrada(self):
        with pytest.raises(HTTPException) as exc:
            ensure_attempt_owner(None, _user("user-1"))
        assert exc.value.status_code == 404

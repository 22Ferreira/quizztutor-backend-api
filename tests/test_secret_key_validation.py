"""Testes da validação de SECRET_KEY em produção (app/config.py).

Achado em auditoria de segurança: a checagem antiga só rejeitava a
string exata "change-me" e o tamanho — o placeholder real do
.env.prod ("TROQUE_POR_CHAVE_FORTE_DE_64_CHARS") tem 34 caracteres,
passava batido. Testes usam monkeypatch em os.environ (o validador lê
ENV diretamente de lá, não de settings) pra simular produção sem
precisar de um .env de verdade.
"""
import pytest

from app.config import Settings


def _make_settings(secret_key: str, monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    return Settings(SECRET_KEY=secret_key, ENV="prod")


class TestSecretKeyValidation:
    def test_chave_forte_de_verdade_passa(self, monkeypatch):
        forte = "a" * 32 + "b" * 32  # 64 chars, sem nenhum marcador de placeholder
        s = _make_settings(forte, monkeypatch)
        assert s.SECRET_KEY == forte

    def test_placeholder_exato_antigo_e_rejeitado(self, monkeypatch):
        with pytest.raises(ValueError):
            _make_settings("change-me", monkeypatch)

    def test_placeholder_real_do_env_prod_e_rejeitado(self, monkeypatch):
        # Esse é o valor literal que vem no .env.prod do repositório —
        # tinha 34 chars e passava despercebido pela checagem antiga.
        with pytest.raises(ValueError):
            _make_settings("TROQUE_POR_CHAVE_FORTE_DE_64_CHARS", monkeypatch)

    def test_curta_demais_e_rejeitada(self, monkeypatch):
        with pytest.raises(ValueError):
            _make_settings("curta", monkeypatch)

    def test_dev_aceita_qualquer_coisa(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        s = Settings(SECRET_KEY="change-me", ENV="dev")
        assert s.SECRET_KEY == "change-me"

"""
Cifra/decifra as chaves de API guardadas no banco (SystemSecret).

Por que cifrar: se alguém tiver acesso só ao banco de dados (um dump,
um backup vazado), as chaves de IA não devem estar legíveis ali. A
chave mestra que cifra/decifra fica SOMENTE no .env do servidor —
nunca no banco — então um vazamento de banco sozinho não expõe nada.

Gerar uma chave mestra nova (rodar uma vez, guardar no .env como
SECRETS_ENCRYPTION_KEY): python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet | None:
    key = settings.SECRETS_ENCRYPTION_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        logger.error("SECRETS_ENCRYPTION_KEY inválida — não é uma chave Fernet válida")
        return None


def encrypt_secret(plain_value: str) -> str:
    f = _get_fernet()
    if not f:
        raise RuntimeError(
            "SECRETS_ENCRYPTION_KEY não configurada no servidor — "
            "não é possível salvar chaves de API pelo admin sem ela."
        )
    return f.encrypt(plain_value.encode()).decode()


def decrypt_secret(encrypted_value: str) -> str | None:
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.decrypt(encrypted_value.encode()).decode()
    except InvalidToken:
        logger.warning("Falha ao decifrar um SystemSecret — chave mestra mudou ou dado corrompido")
        return None


def mask_secret(plain_value: str) -> str:
    """Mostra só os últimos 4 caracteres — nunca a chave inteira de volta pra tela."""
    if len(plain_value) <= 4:
        return "••••"
    return "••••" + plain_value[-4:]

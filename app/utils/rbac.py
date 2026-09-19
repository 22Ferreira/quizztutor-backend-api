"""
RBAC com cache de usuário em memória (TTLCache).
Reduz ~40% das queries de autenticação em alta concorrência.
Cache invalidado ao banir, alterar role ou fazer logout.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from cachetools import TTLCache

from app.db.session import get_db
from app.utils.security import decode_token
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Cache: até 1000 usuários, expira em 60s
# Chave: "{user_id}:{token_version}"
_user_cache: TTLCache = TTLCache(maxsize=1000, ttl=60)


def invalidate_user_cache(user_id: str) -> None:
    """Remover do cache ao banir, alterar role ou revogar token."""
    keys = [k for k in list(_user_cache.keys()) if k.startswith(f"{user_id}:")]
    for k in keys:
        _user_cache.pop(k, None)


async def get_optional_user(
    token: str | None = Depends(oauth2_optional),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None
    try:
        data = decode_token(token)
    except ValueError:
        return None
    if data.type != "access":
        return None

    tv = int(data.tv) if data.tv is not None else 0
    cache_key = f"{data.sub}:{tv}"

    cached = _user_cache.get(cache_key)
    if cached is not None:
        return cached

    q = await db.execute(select(User).where(User.id == data.sub))
    user = q.scalar_one_or_none()
    if not user or not user.active:
        return None
    if data.tv is not None and hasattr(user, "token_version") and int(user.token_version) != tv:
        return None

    _user_cache[cache_key] = user
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        data = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if data.type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    tv = int(data.tv) if data.tv is not None else 0
    cache_key = f"{data.sub}:{tv}"

    cached = _user_cache.get(cache_key)
    if cached is not None:
        return cached

    q = await db.execute(select(User).where(User.id == data.sub))
    user = q.scalar_one_or_none()
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")
    if data.tv is not None and hasattr(user, "token_version") and int(user.token_version) != tv:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    _user_cache[cache_key] = user
    return user


def require_roles(*roles: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user
    return _dep


def ensure_attempt_owner(attempt, me: User | None) -> None:
    """Bloqueia acesso a uma tentativa (attempt) de OUTRO usuário logado.

    Rotas de ação em attempts.py/tutor.py/chat.py carregavam a Attempt só
    pelo ID da URL, sem checar se ela pertence a quem está chamando —
    qualquer um que soubesse/adivinhasse um attempt_id podia ver a
    questão atual, responder, gastar dica ou conversar no chat de outra
    pessoa (achado em auditoria de segurança).

    Tentativa de CONVIDADO (participant_user_id None, fluxo de link
    público/e-mail sem login) não tem dono pra checar — o próprio ID já
    funciona como credencial nesse caso, do jeito que sempre funcionou.
    Só bloqueia quando a tentativa pertence a um usuário logado de
    verdade e quem está chamando não é esse mesmo usuário.
    """
    if attempt is None:
        # attempt_id apontava pra algo que não existe mais (ex: thread
        # órfã) — trata igual "não encontrada", não deixa passar batido.
        raise HTTPException(status_code=404, detail="Tentativa não encontrada")
    if attempt.participant_user_id is not None:
        if not me or me.id != attempt.participant_user_id:
            raise HTTPException(status_code=403, detail="Você não tem acesso a esta tentativa")

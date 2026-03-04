from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.security import decode_token
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


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
    q = await db.execute(select(User).where(User.id == data.sub))
    user = q.scalar_one_or_none()
    if not user or not user.active:
        return None
    if data.tv is not None and hasattr(user, "token_version") and int(user.token_version) != int(data.tv):
        return None
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
    q = await db.execute(select(User).where(User.id == data.sub))
    user = q.scalar_one_or_none()
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")
    if data.tv is not None and hasattr(user, "token_version") and int(user.token_version) != int(data.tv):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    return user


def require_roles(*roles: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user
    return _dep

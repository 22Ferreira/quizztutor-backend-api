from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
from pydantic import BaseModel
from app.config import settings

# Configuração do bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
BCRYPT_MAX_LEN = 72  

class TokenData(BaseModel):
    sub: str
    role: str
    type: str
    exp: int
    tv: int | None = None


def hash_password(password: str) -> str:
    """
    Trunca a senha para 72 bytes antes de gerar o hash, para evitar erros do bcrypt.
    """
    truncated = password[:BCRYPT_MAX_LEN]
    return pwd_context.hash(truncated)


def verify_password(password: str, hashed: str) -> bool:
    """
    Trunca a senha antes de verificar, para compatibilidade com hash gerado pelo bcrypt.
    """
    truncated = password[:BCRYPT_MAX_LEN]
    return pwd_context.verify(truncated, hashed)


def _create_token(subject: str, role: str, token_type: str, expires_delta: timedelta, token_version: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + expires_delta
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    return _create_token(user_id, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), token_version)


def create_refresh_token(user_id: str, role: str, token_version: int = 0) -> str:
    return _create_token(user_id, role, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), token_version)

def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return TokenData(**payload)
    except JWTError as e:
        raise ValueError("Invalid token") from e
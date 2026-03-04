from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.rbac import get_current_user
from app.schemas.auth import LoginRequest, TokenResponse, RegisterRequest, RefreshRequest, RequestPasswordReset, ResetPasswordRequest, ChangePasswordRequest
from app.models.user import User, UserRole
from app.models.password_reset import PasswordResetToken
import hashlib
from datetime import datetime, timezone
from app.utils.security import verify_password, hash_password, create_access_token, create_refresh_token, decode_token
from app.utils.rate_limit import rate_limiter
from app.config import settings
from app.services.audit import event, audit
from app.services.emailer import send_email
from app.config import settings
from app.schemas.auth import UserResponse
router = APIRouter(prefix="/auth", tags=["auth"])
@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role.value
    )

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.hit(ip, "login", settings.RL_LOGIN_PER_MIN):
        raise HTTPException(status_code=429, detail="Too many requests")
    q = await db.execute(select(User).where(User.email == payload.email))
    user = q.scalar_one_or_none()
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        await event(db, user_id=user.id if user else None, event_name="LOGIN_FAIL", meta={"email": payload.email, "ip": ip})
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    access = create_access_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    refresh = create_refresh_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    await event(db, user_id=user.id, event_name="LOGIN_OK", meta={"ip": ip})
    await db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh)

@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(User).where(User.email == payload.email))
    if q.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    user = User(email=payload.email, name=payload.name, password_hash=hash_password(payload.password), role=UserRole.ALUNO)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    access = create_access_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    refresh = create_refresh_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    return TokenResponse(access_token=access, refresh_token=refresh)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if data.type != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    q = await db.execute(select(User).where(User.id == data.sub))
    user = q.scalar_one_or_none()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User inactive")
    access = create_access_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    refresh = create_refresh_token(str(user.id), user.role.value, int(getattr(user,'token_version',0)))
    return TokenResponse(access_token=access, refresh_token=refresh)

@router.post("/request-password-reset")
async def request_password_reset(payload: RequestPasswordReset, request: Request, db: AsyncSession = Depends(get_db)):
    # Always return ok (não revela se email existe)
    q = await db.execute(select(User).where(User.email == payload.email))
    user = q.scalar_one_or_none()
    if user and user.active:
        raw, tok = PasswordResetToken.new(user.id, ttl_minutes=settings.PASSWORD_RESET_TTL_MIN)
        db.add(tok)
        link = f"{settings.APP_PUBLIC_URL.rstrip('/')}/reset-password?token={raw}"
        body = f"Você solicitou troca de senha.\n\nAbra o link para definir uma nova senha (expira em {settings.PASSWORD_RESET_TTL_MIN} minutos):\n{link}\n\nSe não foi você, ignore."
        await send_email(user.email, "Recuperação de senha", body)
        await audit(db, user.id, "REQUEST_PASSWORD_RESET", "User", user.id, after={"ip": request.client.host if request.client else None})
        await event(db, user.id, "PASSWORD_RESET_REQUESTED", {"ip": request.client.host if request.client else None})
        await db.commit()
    return {"message": "ok"}

@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    q = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    pr = q.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=400, detail="Token inválido")
    if pr.used_at is not None:
        raise HTTPException(status_code=400, detail="Token já usado")
    if datetime.now(timezone.utc) >= pr.expires_at:
        raise HTTPException(status_code=400, detail="Token expirado")
    user = await db.get(User, pr.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=400, detail="Usuário inválido")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # revoke all tokens by bump token_version
    if hasattr(user, "token_version"):
        user.token_version = int(user.token_version) + 1
    pr.used_at = datetime.now(timezone.utc)
    await audit(db, user.id, "RESET_PASSWORD", "User", user.id, after={"ip": request.client.host if request.client else None})
    await event(db, user.id, "PASSWORD_RESET_DONE", {"ip": request.client.host if request.client else None})
    await db.commit()
    return {"message": "ok"}

@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, me.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual inválida")
    me.password_hash = hash_password(payload.new_password)
    me.must_change_password = False
    if hasattr(me, "token_version"):
        me.token_version = int(me.token_version) + 1
    await audit(db, me.id, "CHANGE_PASSWORD", "User", me.id, after={})
    await db.commit()
    return {"message":"ok"}

@router.post("/revoke-sessions")
async def revoke_sessions(db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    # user revokes own sessions
    if hasattr(me, "token_version"):
        me.token_version = int(me.token_version) + 1
    await audit(db, me.id, "REVOKE_SESSIONS", "User", me.id, after={})
    await db.commit()
    return {"message":"ok"}

@router.post("/logout")
async def logout():
    # Stateless JWT: logout real seria por blacklist/token version. Aqui devolvemos OK.
    return {"message": "ok"}

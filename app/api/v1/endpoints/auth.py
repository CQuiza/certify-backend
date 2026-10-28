"""OAuth2 password flow (token + refresh) y registro público de estudiantes."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db, get_db_public, get_db_unscoped, set_rls_context
from app.core.tenant import make_tenant_token, reset_tenant_context
from app.core.rate_limit import limiter
from app.core.security import (
    CSRF_COOKIE_NAME,
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    get_password_hash,
    hash_refresh_token,
    refresh_token_expires_at,
    validate_password_strength,
)
from app.core.settings import get_settings
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.schemas.token import RefreshRequest, Token
from app.schemas.user import UserRead
from app.services.user_service import user_service

router = APIRouter(tags=["auth"])

logger = logging.getLogger(__name__)


def _set_csrf_cookie(response: Response, settings, token: str) -> None:
    """Cookie legible por JS para el patrón double-submit."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
        domain=settings.cookie_domain,
    )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., max_length=255)
    first_last_name: str = Field(default="", max_length=255)
    second_last_name: str | None = Field(default=None, max_length=255)
    identity_type: str = "CC"
    identity_number: str = Field(..., max_length=50)
    phone_number: str = Field(..., max_length=20)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=Token)
@limiter.limit("5/minute")
async def register_student(
    request: Request,
    response: Response,
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_public)],
) -> Token:
    """Registro público de estudiantes (compra autónoma)."""
    email = str(body.email).strip().lower()
    if await user_repository.get_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correo ya está registrado")
    if await user_repository.get_by_identity_number(db, body.identity_number):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El número de identidad ya está registrado")
    if await user_repository.get_by_phone_number(db, body.phone_number):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El teléfono ya está registrado")

    pw_errors = validate_password_strength(body.password)
    if pw_errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(pw_errors))

    user = await user_repository.create(
        db,
        email=email,
        password_hash=get_password_hash(body.password),
        name=body.name.strip(),
        first_last_name=body.first_last_name.strip() or None,
        second_last_name=body.second_last_name,
        role="student",
        identity_type=body.identity_type,
        identity_number=body.identity_number,
        phone_number=body.phone_number,
    )

    token = create_access_token(
        subject=user.id, extra_claims={"tenant_id": user.tenant_id, "role": user.role}
    )
    refresh_token = generate_refresh_token()
    user.refresh_token_hash = hash_refresh_token(refresh_token)
    user.refresh_token_expires_at = refresh_token_expires_at()
    db.add(user)
    await db.flush()

    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    _set_csrf_cookie(response, settings, generate_csrf_token())
    logger.info("Estudiante registrado — id=%s email=%s", user.id, user.email)
    return Token(access_token=token, refresh_token=refresh_token)


@router.post("/auth/token", response_model=Token, summary="Obtener token OAuth2")
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db_public)],
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user: User | None
    try:
        user = await user_service.authenticate(db, form.username, form.password)
    except PermissionError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    if not user:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        subject=user.id, extra_claims={"tenant_id": user.tenant_id, "role": user.role}
    )
    settings = get_settings()
    refresh_token = generate_refresh_token()
    user.refresh_token_hash = hash_refresh_token(refresh_token)
    user.refresh_token_expires_at = refresh_token_expires_at()
    db.add(user)
    await db.flush()

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    _set_csrf_cookie(response, settings, generate_csrf_token())
    return Token(access_token=token, refresh_token=refresh_token)


@router.post("/auth/refresh", summary="Rotar access token con refresh token")
@limiter.limit("5/minute")
async def refresh_access_token(
    request: Request,
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
) -> JSONResponse:
    hashed = hash_refresh_token(body.refresh_token)
    r = await db.execute(
        select(User).where(
            User.refresh_token_hash == hashed,
            User.refresh_token_expires_at > datetime.now(UTC),
        )
    )
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    # El refresh token es global: después de localizar al usuario, se opera
    # dentro de su tenant para mantener el aislamiento.
    tenant_token = make_tenant_token(user.tenant_id)
    try:
        await set_rls_context(db, user.tenant_id)
        new_access = create_access_token(
            subject=user.id, extra_claims={"tenant_id": user.tenant_id, "role": user.role}
        )
        new_refresh = generate_refresh_token()
        user.refresh_token_hash = hash_refresh_token(new_refresh)
        user.refresh_token_expires_at = refresh_token_expires_at()
        db.add(user)
        await db.flush()
    finally:
        reset_tenant_context(tenant_token)

    settings = get_settings()
    content = Token(access_token=new_access, refresh_token=new_refresh).model_dump()
    resp = JSONResponse(content=content)
    resp.set_cookie(
        key="access_token",
        value=new_access,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    _set_csrf_cookie(resp, settings, generate_csrf_token())
    return resp


@router.post("/auth/logout", summary="Invalidar refresh token")
async def logout(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    current.refresh_token_hash = None
    current.refresh_token_expires_at = None
    db.add(current)
    await db.flush()
    settings = get_settings()
    resp = JSONResponse(content={"message": "Sesión cerrada"})
    resp.delete_cookie(key="access_token", httponly=True, path="/api/v1", domain=settings.cookie_domain)
    resp.delete_cookie(key=CSRF_COOKIE_NAME, path="/", domain=settings.cookie_domain)
    resp.delete_cookie(key="acting_tenant", httponly=True, path="/api/v1", domain=settings.cookie_domain)
    return resp


@router.get("/auth/me", response_model=UserRead, summary="Usuario autenticado")
async def me(current: Annotated[User, Depends(get_current_user)]) -> User:
    return current

"""OAuth2 password flow (token + refresh) y registro público de estudiantes."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db_public, get_db_unscoped, set_rls_context
from app.core.rate_limit import limiter
from app.core.security import (
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    create_access_token,
    generate_csrf_token,
    get_password_hash,
    validate_password_strength,
)
from app.core.settings import get_settings
from app.core.tenant import make_tenant_token, reset_tenant_context
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.schemas.token import Token
from app.schemas.user import UserRead
from app.services import refresh_session_service, turnstile_service
from app.services.user_service import user_service

router = APIRouter(tags=["auth"])

logger = logging.getLogger(__name__)

REGISTRATION_FAILED_DETAIL = (
    "No pudimos completar el registro. Intenta de nuevo o inicia sesión."
)


def _set_access_cookie(response: Response, token: str, settings) -> None:
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


def _set_refresh_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=refresh_session_service.REFRESH_DAYS * 24 * 3600,
        path="/api/v1/auth",
        domain=settings.cookie_domain,
    )


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


def _clear_auth_cookies(response: Response, settings) -> None:
    response.delete_cookie(
        key="access_token",
        httponly=True,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        path="/api/v1/auth",
        domain=settings.cookie_domain,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        domain=settings.cookie_domain,
    )
    response.delete_cookie(
        key="acting_tenant",
        httponly=True,
        path="/api/v1",
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
    turnstile_token: str | None = Field(default=None, max_length=2048)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=Token)
@limiter.limit("3/minute")
@limiter.limit("10/hour")
async def register_student(
    request: Request,
    response: Response,
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_public)],
) -> Token:
    """Registro público de estudiantes (compra autónoma)."""
    if not await turnstile_service.verify_token(body.turnstile_token):
        logger.warning("Registro rechazado: verificación CAPTCHA fallida")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_FAILED_DETAIL,
        )

    email = str(body.email).strip().lower()
    identity_number = body.identity_number.strip()
    phone_number = body.phone_number.strip()
    if await user_repository.exists_by_registration_identifiers(
        db,
        email=email,
        identity_number=identity_number,
        phone_number=phone_number,
    ):
        logger.info("Registro rechazado: identificador duplicado")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_FAILED_DETAIL,
        )

    pw_errors = validate_password_strength(body.password)
    if pw_errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(pw_errors))

    try:
        user = await user_repository.create(
            db,
            email=email,
            password_hash=get_password_hash(body.password),
            name=body.name.strip(),
            first_last_name=body.first_last_name.strip() or None,
            second_last_name=body.second_last_name,
            role="student",
            identity_type=body.identity_type,
            identity_number=identity_number,
            phone_number=phone_number,
        )
    except IntegrityError as exc:
        logger.warning("Registro rechazado: conflicto de unicidad")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_FAILED_DETAIL,
        ) from exc

    access_token = create_access_token(
        subject=user.id, extra_claims={"tenant_id": user.tenant_id, "role": user.role}
    )
    refresh_token, _ = await refresh_session_service.issue(db, user, request=request)

    settings = get_settings()
    _set_access_cookie(response, access_token, settings)
    _set_refresh_cookie(response, refresh_token, settings)
    _set_csrf_cookie(response, settings, generate_csrf_token())
    logger.info("Estudiante registrado — id=%s email=%s", user.id, user.email)
    return Token(access_token=access_token)


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

    access_token = create_access_token(
        subject=user.id, extra_claims={"tenant_id": user.tenant_id, "role": user.role}
    )
    refresh_token, _ = await refresh_session_service.issue(db, user, request=request)

    settings = get_settings()
    _set_access_cookie(response, access_token, settings)
    _set_refresh_cookie(response, refresh_token, settings)
    _set_csrf_cookie(response, settings, generate_csrf_token())
    return Token(access_token=access_token)


@router.post("/auth/refresh", summary="Rotar access token con refresh token")
@limiter.limit("5/minute")
async def refresh_access_token(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
) -> JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    settings = get_settings()

    if not token:
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Refresh token ausente"},
        )
        _clear_auth_cookies(resp, settings)
        return resp

    session = await refresh_session_service.get_by_token(db, token, for_update=True)
    if session is None:
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Refresh token inválido"},
        )
        _clear_auth_cookies(resp, settings)
        return resp

    now = datetime.now(UTC)
    expires_at = (
        session.expires_at.replace(tzinfo=UTC)
        if session.expires_at.tzinfo is None
        else session.expires_at
    )
    family_expires_at = (
        session.family_expires_at.replace(tzinfo=UTC)
        if session.family_expires_at.tzinfo is None
        else session.family_expires_at
    )

    if session.revoked_at is not None or session.replaced_by_id is not None:
        await refresh_session_service.revoke_family(db, session.family_id)
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Refresh token reutilizado"},
        )
        _clear_auth_cookies(resp, settings)
        return resp

    if expires_at <= now or family_expires_at <= now:
        await refresh_session_service.revoke_session(db, session, reason="expired")
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Refresh token expirado"},
        )
        _clear_auth_cookies(resp, settings)
        return resp

    user = await user_repository.get_by_id(db, session.user_id)
    if user is None or not user.is_active:
        await refresh_session_service.revoke_session(db, session, reason="user_inactive")
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Usuario inactivo o inexistente"},
        )
        _clear_auth_cookies(resp, settings)
        return resp

    tenant_token = make_tenant_token(user.tenant_id)
    try:
        await set_rls_context(db, user.tenant_id)
        new_refresh, _ = await refresh_session_service.rotate(
            db, session, user, request=request
        )
        new_access = create_access_token(
            subject=user.id,
            extra_claims={"tenant_id": user.tenant_id, "role": user.role},
        )
    finally:
        reset_tenant_context(tenant_token)

    resp = JSONResponse(content=Token(access_token=new_access).model_dump())
    _set_access_cookie(resp, new_access, settings)
    _set_refresh_cookie(resp, new_refresh, settings)
    _set_csrf_cookie(resp, settings, generate_csrf_token())
    return resp


@router.post("/auth/logout", summary="Invalidar refresh token")
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
) -> JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token:
        session = await refresh_session_service.get_by_token(db, token)
        if session is not None:
            await refresh_session_service.revoke_session(db, session, reason="logout")

    settings = get_settings()
    resp = JSONResponse(content={"message": "Sesión cerrada"})
    _clear_auth_cookies(resp, settings)
    return resp


@router.get("/auth/me", response_model=UserRead, summary="Usuario autenticado")
async def me(current: Annotated[User, Depends(get_current_user)]) -> User:
    return current

"""Dependencias: OAuth2 JWT y usuarios opcionales."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.settings import get_settings
from app.core.database import AsyncSessionLocal
from app.core.legal import EULA_DOCUMENT, EULA_VERSION
from app.core.security import decode_token
from app.core.tenant import unscoped_ctx
from app.models.user import User
from app.repositories.user_consent_repository import user_consent_repository
from app.repositories.user_repository import user_repository

_settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{_settings.api_v1_prefix}/auth/token",
    auto_error=False,
)

_CONSENT_EXEMPT_PATHS = {
    f"{_settings.api_v1_prefix}/auth/me",
    f"{_settings.api_v1_prefix}/auth/accept-eula",
    f"{_settings.api_v1_prefix}/auth/refresh",
    f"{_settings.api_v1_prefix}/auth/logout",
}


async def get_token_from_request(request: Request) -> str:
    token = await oauth2_scheme(request)
    if token:
        return token
    token = request.cookies.get("access_token")
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_token_from_request(request: Request) -> str | None:
    token = await oauth2_scheme(request)
    if token:
        return token
    return request.cookies.get("access_token")


def _decode_user_id(token: str) -> int:
    try:
        payload = decode_token(token)
        return int(payload.get("sub"))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(get_token_from_request)],
) -> User:
    uid = _decode_user_id(token)
    # El usuario se carga sin scope de tenant (el id es global) para que el
    # superuser pueda ejercer en cualquier tenant (impersonación). El bloque
    # unscoped_ctx restaura el contexto previo al terminar la consulta.
    consent = None
    async with AsyncSessionLocal() as session:
        async with unscoped_ctx():
            user = await user_repository.get_by_id(session, uid)
            if user and user.is_active and user.role == "student":
                consent = await user_consent_repository.get_current(
                    session,
                    user_id=user.id,
                    document=EULA_DOCUMENT,
                    version=EULA_VERSION,
                )
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o inexistente",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.eula_pending = False
    request.state.eula_accepted_at = None
    if user.role == "student":
        request.state.eula_pending = consent is None
        request.state.eula_accepted_at = consent.accepted_at if consent else None
        path = request.url.path.rstrip("/")
        if request.state.eula_pending and path not in _CONSENT_EXEMPT_PATHS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "consent_required",
                    "document": EULA_DOCUMENT,
                    "version": EULA_VERSION,
                },
            )
    return user


async def get_optional_user(
    token: Annotated[str | None, Depends(get_optional_token_from_request)],
) -> User | None:
    if not token:
        return None
    try:
        uid = _decode_user_id(token)
    except HTTPException:
        return None
    async with AsyncSessionLocal() as session:
        async with unscoped_ctx():
            user = await user_repository.get_by_id(session, uid)
    if user is None or not user.is_active:
        return None
    return user

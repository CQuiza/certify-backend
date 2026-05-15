"""Dependencias: OAuth2 JWT y usuarios opcionales."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user_repository import user_repository

_settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{_settings.api_v1_prefix}/auth/token",
    auto_error=True,
)

oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{_settings.api_v1_prefix}/auth/token",
    auto_error=False,
)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    try:
        payload = decode_token(token)
        uid = int(payload.get("sub"))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await user_repository.get_by_id(db, uid)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o inexistente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_optional)],
) -> User | None:
    if not token:
        return None
    try:
        payload = decode_token(token)
        uid = int(payload.get("sub"))
    except (ValueError, TypeError, KeyError):
        return None
    user = await user_repository.get_by_id(db, uid)
    if not user or not user.is_active:
        return None
    return user

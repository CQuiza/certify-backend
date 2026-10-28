"""Ciclo de vida de refresh tokens por dispositivo."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, hash_refresh_token
from app.models.refresh_session import RefreshSession
from app.models.user import User

logger = logging.getLogger(__name__)

REFRESH_DAYS = 30
FAMILY_MAX_DAYS = 90


def _client_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else None
    )
    return ip, request.headers.get("user-agent")


async def issue(
    db: AsyncSession,
    user: User,
    *,
    request: Request | None = None,
    family_id: UUID | None = None,
    family_expires_at: datetime | None = None,
) -> tuple[str, RefreshSession]:
    """Crea una sesión nueva y devuelve el token en claro (solo se entrega una vez)."""
    now = datetime.now(UTC)
    token = generate_refresh_token()
    ip, user_agent = _client_meta(request)
    session = RefreshSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        family_id=family_id or uuid4(),
        token_hash=hash_refresh_token(token),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=REFRESH_DAYS),
        family_expires_at=family_expires_at or now + timedelta(days=FAMILY_MAX_DAYS),
        user_agent=user_agent,
        ip=ip,
    )
    db.add(session)
    await db.flush()
    return token, session


async def get_by_token(
    db: AsyncSession, token: str, *, for_update: bool = False
) -> RefreshSession | None:
    hashed = hash_refresh_token(token)
    statement = (
        select(RefreshSession).where(RefreshSession.token_hash == hashed).limit(1)
    )
    if for_update:
        # Serializa rotaciones concurrentes del mismo token (multi-pestaña/dispositivo).
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def rotate(
    db: AsyncSession,
    session: RefreshSession,
    user: User,
    *,
    request: Request | None = None,
) -> tuple[str, RefreshSession]:
    """Invalida la sesión actual y emite una nueva dentro de la misma familia."""
    now = datetime.now(UTC)
    token, new_session = await issue(
        db,
        user,
        request=request,
        family_id=session.family_id,
        family_expires_at=session.family_expires_at,
    )
    session.revoked_at = now
    session.revoked_reason = "rotated"
    session.replaced_by_id = new_session.id
    session.last_used_at = now
    db.add(session)
    await db.flush()
    return token, new_session


async def revoke_session(
    db: AsyncSession, session: RefreshSession, reason: str = "logout"
) -> None:
    session.revoked_at = datetime.now(UTC)
    session.revoked_reason = reason
    db.add(session)
    await db.flush()


async def revoke_family(
    db: AsyncSession, family_id: UUID, reason: str = "reuse_detected"
) -> None:
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
    logger.warning("Familia de refresh revocada — family=%s reason=%s", family_id, reason)


async def revoke_all_for_user(
    db: AsyncSession, user_id: int, reason: str = "password_changed"
) -> int:
    result = await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
    return result.rowcount or 0

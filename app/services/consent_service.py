"""Registro y consulta de consentimientos legales."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.legal import EULA_DOCUMENT, EULA_VERSION
from app.models.user import User
from app.models.user_consent import UserConsent
from app.repositories.user_consent_repository import user_consent_repository


def _request_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else None
    )
    return ip, request.headers.get("user-agent")


async def current_eula(
    db: AsyncSession, user_id: int
) -> UserConsent | None:
    return await user_consent_repository.get_current(
        db,
        user_id=user_id,
        document=EULA_DOCUMENT,
        version=EULA_VERSION,
    )


async def record_eula(
    db: AsyncSession,
    user: User,
    request: Request | None = None,
) -> UserConsent:
    existing = await current_eula(db, user.id)
    if existing is not None:
        return existing

    ip, user_agent = _request_meta(request)
    try:
        async with db.begin_nested():
            return await user_consent_repository.create(
                db,
                tenant_id=user.tenant_id,
                user_id=user.id,
                document=EULA_DOCUMENT,
                version=EULA_VERSION,
                ip=ip,
                user_agent=user_agent,
            )
    except IntegrityError:
        existing = await current_eula(db, user.id)
        if existing is not None:
            return existing
        raise


async def eula_accepted_at(db: AsyncSession, user_id: int) -> datetime | None:
    consent = await current_eula(db, user_id)
    return consent.accepted_at if consent else None

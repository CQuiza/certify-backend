"""Acceso a consentimientos legales."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_consent import UserConsent


class UserConsentRepository:
    async def get_current(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        document: str,
        version: str,
    ) -> UserConsent | None:
        result = await db.execute(
            select(UserConsent)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.document == document,
                UserConsent.version == version,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, db: AsyncSession, user_id: int) -> list[UserConsent]:
        result = await db.execute(
            select(UserConsent)
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.accepted_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        *,
        tenant_id: int,
        user_id: int,
        document: str,
        version: str,
        ip: str | None,
        user_agent: str | None,
    ) -> UserConsent:
        row = UserConsent(
            tenant_id=tenant_id,
            user_id=user_id,
            document=document,
            version=version,
            accepted_at=datetime.now(UTC),
            ip=ip,
            user_agent=user_agent,
        )
        db.add(row)
        await db.flush()
        return row


user_consent_repository = UserConsentRepository()

"""Repositorio de plantillas de correo personalizables."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_template import EmailTemplate


class EmailTemplateRepository:
    async def list_by_settings(
        self, db: AsyncSession, platform_settings_id: int
    ) -> Sequence[EmailTemplate]:
        r = await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.platform_settings_id == platform_settings_id
            )
        )
        return r.scalars().all()

    async def get_by_kind(
        self, db: AsyncSession, platform_settings_id: int, kind: str
    ) -> EmailTemplate | None:
        r = await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.platform_settings_id == platform_settings_id,
                EmailTemplate.kind == kind,
            )
        )
        return r.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        platform_settings_id: int,
        kind: str,
        subject: str,
        body_html: str,
        is_enabled: bool,
        updated_by: int | None = None,
    ) -> EmailTemplate:
        row = await self.get_by_kind(db, platform_settings_id, kind)
        if row is None:
            row = EmailTemplate(
                platform_settings_id=platform_settings_id,
                kind=kind,
                subject=subject,
                body_html=body_html,
                is_enabled=is_enabled,
                updated_by=updated_by,
            )
            db.add(row)
        else:
            row.subject = subject
            row.body_html = body_html
            row.is_enabled = is_enabled
            row.updated_by = updated_by
        await db.flush()
        await db.refresh(row)
        return row

    async def delete_by_kind(
        self, db: AsyncSession, platform_settings_id: int, kind: str
    ) -> bool:
        row = await self.get_by_kind(db, platform_settings_id, kind)
        if row is None:
            return False
        await db.delete(row)
        await db.flush()
        return True


email_template_repository = EmailTemplateRepository()
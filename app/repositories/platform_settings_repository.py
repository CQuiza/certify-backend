"""Repositorio de configuración de plataforma (una fila por tenant)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_settings import PlatformSettings


class PlatformSettingsRepository:
    async def get_by_tenant(
        self, db: AsyncSession, tenant_id: int
    ) -> PlatformSettings | None:
        r = await db.execute(
            select(PlatformSettings).where(PlatformSettings.tenant_id == tenant_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, db: AsyncSession, tenant_id: int) -> PlatformSettings:
        row = await self.get_by_tenant(db, tenant_id)
        if row is not None:
            return row
        row = PlatformSettings(tenant_id=tenant_id)
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def update(
        self, db: AsyncSession, row: PlatformSettings, fields: dict[str, object]
    ) -> PlatformSettings:
        allowed = {
            "organization_name",
            "dashboard_message",
            "branding_logo_object_key",
            "smtp_enabled",
            "smtp_host",
            "smtp_port",
            "smtp_user",
            "smtp_password_encrypted",
            "smtp_tls",
            "email_from",
            "email_from_name",
            "updated_by",
        }
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        await db.flush()
        await db.refresh(row)
        return row


platform_settings_repository = PlatformSettingsRepository()
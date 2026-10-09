"""Servicio de tenants (organizaciones)."""

from __future__ import annotations

import logging
import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.tenant import tenant_ctx
from app.models.tenant import Tenant
from app.repositories.platform_settings_repository import platform_settings_repository
from app.repositories.tenant_repository import tenant_repository
from app.repositories.user_repository import user_repository

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")


def _valid_slug(slug: str) -> bool:
    return bool(slug and _SLUG_RE.fullmatch(slug))


def public_origin(tenant: Tenant, settings=None) -> str:
    """Origen público de URLs del tenant (sin /api/v1)."""
    settings = settings or get_settings()
    domain = (tenant.domain or "").strip().lower()
    slug = (tenant.slug or "").strip().lower()
    if domain:
        return f"https://{domain}"
    if settings.root_domain and slug and slug != settings.default_tenant_slug:
        return f"https://{slug}.{settings.root_domain}"
    return settings.base_url.rstrip("/")


class TenantService:
    async def get_or_404(self, db: AsyncSession, tenant_id: int) -> Tenant:
        tenant = await tenant_repository.get_by_id(db, tenant_id)
        if tenant is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado"
            )
        return tenant

    async def current_public_origin(self, db: AsyncSession) -> str:
        from app.core.tenant import current_tenant_id, resolve_default_tenant_id

        tenant_id = current_tenant_id()
        if tenant_id is None:
            tenant_id = await resolve_default_tenant_id(db)
        return await self.origin_for_tenant_id(db, tenant_id)

    async def origin_for_tenant_id(self, db: AsyncSession, tenant_id: int | None) -> str:
        """Origen público (sin /api/v1) del tenant; default si no existe."""
        settings = get_settings()
        if tenant_id is None:
            return settings.base_url.rstrip("/")
        tenant = await tenant_repository.get_by_id(db, tenant_id)
        if tenant is None:
            return settings.base_url.rstrip("/")
        return public_origin(tenant)

    async def create_tenant(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        admin_email: str,
        admin_name: str | None = None,
        admin_password: str | None = None,
        created_by: int | None = None,
    ) -> tuple[Tenant, str]:
        from app.core.security import generate_secure_password, get_password_hash

        slug = slug.strip().lower()
        if not _valid_slug(slug):
            raise ValueError("Slug inválido: solo minúsculas, números y guiones")
        if await tenant_repository.get_by_slug(db, slug) is not None:
            raise ValueError("Ya existe una organización con ese slug")

        tenant = await tenant_repository.create(
            db, name=name.strip(), slug=slug, created_by=created_by
        )

        # El scope del tenant recién creado se activa para sembrar sus usuarios.
        async with tenant_ctx(tenant.id):
            admin_password = admin_password or generate_secure_password()
            settings = get_settings()
            admin = await user_repository.create(
                db,
                email=admin_email.strip().lower(),
                password_hash=get_password_hash(admin_password),
                name=admin_name or name.strip(),
                first_last_name="",
                role="admin",
                identity_type="OTHER",
                identity_number=f"ADM-{slug[:40]}",
                phone_number=f"+000{abs(hash(slug)) % 10_000_000_000:010d}",
                is_active=True,
            )

            bot = await user_repository.create(
                db,
                email=settings.system_bot_user_email,
                password_hash=get_password_hash(secrets.token_urlsafe(32)),
                name="System",
                first_last_name="Bot",
                role="admin",
                identity_type="OTHER",
                identity_number=f"BOT-{slug[:40]}",
                phone_number=f"+000{abs(hash(settings.system_bot_user_email)) % 10_000_000_000:010d}",
                is_active=True,
            )

        platform_settings = await platform_settings_repository.get_or_create(db, tenant.id)
        await platform_settings_repository.update(
            db, platform_settings, {"organization_name": name.strip()}
        )

        logger.info(
            "Tenant creado — id=%s slug=%s admin=%s by=%s",
            tenant.id, slug, admin_email, created_by,
        )
        return tenant, admin_password

    async def list_tenants(self, db: AsyncSession) -> list[dict]:
        from app.core.tenant import unscoped_ctx

        tenants = await tenant_repository.list_all(db)
        result: list[dict] = []
        async with unscoped_ctx():
            for t in tenants:
                counts = await self._counts(db, t.id)
                result.append(
                    {
                        "id": t.id,
                        "name": t.name,
                        "slug": t.slug,
                        "domain": t.domain,
                        "is_active": bool(t.is_active),
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        **counts,
                    }
                )
        return result

    async def _counts(self, db: AsyncSession, tenant_id: int) -> dict:
        from app.models.certificate import Certificate
        from app.models.course import Course
        from app.models.user import User

        users = (
            await db.execute(select(func.count(User.id)).where(User.tenant_id == tenant_id))
        ).scalar() or 0
        courses = (
            await db.execute(select(func.count(Course.id)).where(Course.tenant_id == tenant_id))
        ).scalar() or 0
        certificates = (
            await db.execute(select(func.count(Certificate.id)).where(Certificate.tenant_id == tenant_id))
        ).scalar() or 0
        return {
            "total_users": users,
            "total_courses": courses,
            "total_certificates": certificates,
        }

    async def update_status(
        self, db: AsyncSession, tenant_id: int, *, is_active: bool, by: int | None = None
    ) -> Tenant:
        tenant = await self.get_or_404(db, tenant_id)
        tenant = await tenant_repository.update(db, tenant, {"is_active": is_active})
        logger.info("Tenant %s %s — by=%s", tenant_id, "activado" if is_active else "desactivado", by)
        return tenant


tenant_service = TenantService()
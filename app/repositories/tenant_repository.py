"""Repositorio de tenants (organizaciones)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant


class TenantRepository:
    async def get_by_id(self, db: AsyncSession, tenant_id: int) -> Tenant | None:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return r.scalar_one_or_none()

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Tenant | None:
        r = await db.execute(select(Tenant).where(Tenant.slug == slug))
        return r.scalar_one_or_none()

    async def get_by_domain(self, db: AsyncSession, domain: str) -> Tenant | None:
        r = await db.execute(select(Tenant).where(Tenant.domain == domain))
        return r.scalar_one_or_none()

    async def get_default(self, db: AsyncSession, slug: str) -> Tenant | None:
        return await self.get_by_slug(db, slug)

    async def list_all(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 200,
    ) -> Sequence[Tenant]:
        r = await db.execute(
            select(Tenant).order_by(Tenant.id).offset(skip).limit(limit)
        )
        return r.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        domain: str | None = None,
        created_by: int | None = None,
    ) -> Tenant:
        t = Tenant(name=name, slug=slug, domain=domain, created_by=created_by)
        db.add(t)
        await db.flush()
        await db.refresh(t)
        return t

    async def update(self, db: AsyncSession, tenant: Tenant, fields: dict) -> Tenant:
        allowed = {"name", "slug", "domain", "is_active"}
        for k, v in fields.items():
            if k in allowed:
                setattr(tenant, k, v)
        await db.flush()
        await db.refresh(tenant)
        return tenant


tenant_repository = TenantRepository()
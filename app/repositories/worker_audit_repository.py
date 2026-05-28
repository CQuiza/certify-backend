"""Repositorio de auditoría de trabajos en segundo plano."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.worker_audit import WorkerAudit


class WorkerAuditRepository:
    async def list(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WorkerAudit]:
        q = select(WorkerAudit).order_by(WorkerAudit.created_at.desc()).offset(skip).limit(limit)
        r = await db.execute(q)
        return list(r.scalars().all())


worker_audit_repository = WorkerAuditRepository()

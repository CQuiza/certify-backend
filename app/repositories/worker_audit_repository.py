"""Auditoría de trabajos en segundo plano."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.worker_audit import WorkerAudit


class WorkerAuditRepository:
    async def get_by_id(self, db: AsyncSession, audit_id: int) -> WorkerAudit | None:
        r = await db.execute(select(WorkerAudit).where(WorkerAudit.id == audit_id))
        return r.scalar_one_or_none()

    async def list(
        self, db: AsyncSession, *, skip: int = 0, limit: int = 100
    ) -> Sequence[WorkerAudit]:
        r = await db.execute(select(WorkerAudit).offset(skip).limit(limit))
        return r.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        task_name: str,
        status: str,
        started_at: object | None = None,
        finished_at: object | None = None,
        details: str | None = None,
    ) -> WorkerAudit:
        a = WorkerAudit(
            task_name=task_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            details=details,
        )
        db.add(a)
        await db.flush()
        await db.refresh(a)
        return a


worker_audit_repository = WorkerAuditRepository()

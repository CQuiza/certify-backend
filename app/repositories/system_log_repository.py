"""Repositorio de logs de la plataforma."""

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_log import SystemLog


class SystemLogRepository:
    def _apply_filters(
        self,
        q,
        *,
        level: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ):
        if level:
            q = q.where(SystemLog.level == level)
        if source:
            q = q.where(SystemLog.source == source)
        if search:
            pattern = f"%{search}%"
            q = q.where(
                or_(
                    SystemLog.event.ilike(pattern),
                    SystemLog.detail.ilike(pattern),
                    SystemLog.path.ilike(pattern),
                )
            )
        return q

    async def create(
        self,
        db: AsyncSession,
        *,
        level: str,
        source: str,
        event: str,
        detail: str | None = None,
        stacktrace: str | None = None,
        request_id: str | None = None,
        path: str | None = None,
        method: str | None = None,
        status_code: int | None = None,
        user_id: int | None = None,
    ) -> SystemLog:
        row = SystemLog(
            level=level,
            source=source,
            event=event,
            detail=detail,
            stacktrace=stacktrace,
            request_id=request_id,
            path=path,
            method=method,
            status_code=status_code,
            user_id=user_id,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def count(
        self,
        db: AsyncSession,
        *,
        level: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> int:
        q = select(func.count(SystemLog.id))
        q = self._apply_filters(q, level=level, source=source, search=search)
        r = await db.execute(q)
        return r.scalar() or 0

    async def list(
        self,
        db: AsyncSession,
        *,
        level: str | None = None,
        source: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[SystemLog]:
        q = select(SystemLog)
        q = self._apply_filters(q, level=level, source=source, search=search)
        q = q.order_by(SystemLog.created_at.desc()).offset(skip).limit(limit)
        r = await db.execute(q)
        return r.scalars().all()


system_log_repository = SystemLogRepository()
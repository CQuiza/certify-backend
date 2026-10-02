"""Repositorio de solicitudes de certificado en proceso."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_certificate import PendingCertificate


class PendingCertificateRepository:
    async def get_by_id(self, db: AsyncSession, pending_id: int) -> PendingCertificate | None:
        r = await db.execute(
            select(PendingCertificate).where(PendingCertificate.id == pending_id)
        )
        return r.scalar_one_or_none()

    async def get_by_user_and_course(
        self, db: AsyncSession, user_id: int, course_id: int
    ) -> PendingCertificate | None:
        r = await db.execute(
            select(PendingCertificate).where(
                PendingCertificate.user_id == user_id,
                PendingCertificate.course_id == course_id,
            )
        )
        return r.scalar_one_or_none()

    async def list_in_progress_by_course(
        self, db: AsyncSession, course_id: int
    ) -> Sequence[PendingCertificate]:
        r = await db.execute(
            select(PendingCertificate)
            .where(
                PendingCertificate.course_id == course_id,
                PendingCertificate.status == "in_progress",
            )
            .order_by(PendingCertificate.created_at)
        )
        return r.scalars().all()

    async def list_by_user(
        self, db: AsyncSession, user_id: int | None = None
    ) -> Sequence[PendingCertificate]:
        q = select(PendingCertificate).order_by(PendingCertificate.created_at.desc())
        if user_id is not None:
            q = q.where(PendingCertificate.user_id == user_id)
        r = await db.execute(q)
        return r.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        course_id: int,
        certificate_type_id: int | None,
        created_by: int | None,
        issued_at_override=None,
        validity_extension: int | None = None,
        hours: int | None = None,
    ) -> PendingCertificate:
        pc = PendingCertificate(
            user_id=user_id,
            course_id=course_id,
            certificate_type_id=certificate_type_id,
            created_by=created_by,
            issued_at_override=issued_at_override,
            validity_extension=validity_extension,
            hours=hours,
        )
        db.add(pc)
        await db.flush()
        await db.refresh(pc)
        return pc

    async def update(self, db: AsyncSession, pc: PendingCertificate, fields: dict) -> PendingCertificate:
        for k, v in fields.items():
            setattr(pc, k, v)
        await db.flush()
        await db.refresh(pc)
        return pc


pending_certificate_repository = PendingCertificateRepository()
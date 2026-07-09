"""Repositorio de estadísticas para el dashboard."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certificate import Certificate
from app.models.certificate_type import CertificateType
from app.models.course import Course
from app.models.enums import CertificateStatus
from app.models.user import User
from app.schemas.dashboard import DashboardStatsResponse


class DashboardRepository:
    async def get_stats(self, db: AsyncSession) -> DashboardStatsResponse:
        r = await db.execute(select(func.count(User.id)))
        total_users = r.scalar() or 0

        r = await db.execute(select(func.count(Certificate.id)))
        total_certificates = r.scalar() or 0

        r = await db.execute(
            select(func.count(Certificate.id)).where(
                Certificate.status == CertificateStatus.active.value
            )
        )
        active_certificates = r.scalar() or 0

        r = await db.execute(
            select(func.count(Certificate.id)).where(
                Certificate.status == CertificateStatus.expired.value
            )
        )
        expired_certificates = r.scalar() or 0

        r = await db.execute(
            select(func.count(Certificate.id)).where(
                Certificate.status == CertificateStatus.revoked.value
            )
        )
        revoked_certificates = r.scalar() or 0

        r = await db.execute(
            select(func.count(Course.id)).where(Course.status == "published")
        )
        published_courses = r.scalar() or 0

        r = await db.execute(select(func.count(CertificateType.id)))
        certificate_types = r.scalar() or 0

        return DashboardStatsResponse(
            total_users=total_users,
            total_certificates=total_certificates,
            active_certificates=active_certificates,
            expired_certificates=expired_certificates,
            revoked_certificates=revoked_certificates,
            published_courses=published_courses,
            certificate_types=certificate_types,
        )


dashboard_repository = DashboardRepository()

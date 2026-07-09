"""Estadísticas del dashboard."""

from pydantic import BaseModel


class DashboardStatsResponse(BaseModel):
    total_users: int = 0
    total_certificates: int = 0
    active_certificates: int = 0
    expired_certificates: int = 0
    revoked_certificates: int = 0
    published_courses: int = 0
    certificate_types: int = 0

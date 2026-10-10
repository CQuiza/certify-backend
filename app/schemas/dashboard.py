"""Estadísticas del dashboard."""

from pydantic import BaseModel, ConfigDict


class DashboardStatsResponse(BaseModel):
    total_users: int = 0
    total_certificates: int = 0
    active_certificates: int = 0
    expired_certificates: int = 0
    revoked_certificates: int = 0
    published_courses: int = 0
    certificate_types: int = 0


class AdminRead(BaseModel):
    id: int
    name: str
    first_last_name: str | None
    second_last_name: str | None
    email: str
    identity_type: str
    identity_number: str
    phone_number: str
    role: str

    model_config = ConfigDict(from_attributes=True)

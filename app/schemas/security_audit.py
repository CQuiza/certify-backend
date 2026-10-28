"""Esquemas de auditoría de seguridad."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SecurityAuditRead(BaseModel):
    id: int
    actor_id: int | None
    actor_role: str | None
    target_tenant_id: int | None
    target_type: str | None
    target_id: int | None
    action: str
    before: dict | None
    after: dict | None
    ip: str | None
    user_agent: str | None
    request_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SecurityAuditListResponse(BaseModel):
    items: list[SecurityAuditRead]
    total: int

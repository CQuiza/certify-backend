"""Consulta de auditoría de seguridad (solo superusuario)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db_unscoped
from app.models.security_audit import SecurityAudit
from app.models.user import User
from app.schemas.security_audit import SecurityAuditListResponse, SecurityAuditRead

router = APIRouter(prefix="/admin/security-audit", tags=["admin", "audit"])


@router.get("", response_model=SecurityAuditListResponse)
async def list_security_audit(
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
    action: Annotated[str | None, Query()] = None,
    actor_id: Annotated[int | None, Query()] = None,
    target_tenant_id: Annotated[int | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SecurityAuditListResponse:
    if current.role != "superuser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios de plataforma",
        )

    filters = []
    if action:
        filters.append(SecurityAudit.action == action)
    if actor_id is not None:
        filters.append(SecurityAudit.actor_id == actor_id)
    if target_tenant_id is not None:
        filters.append(SecurityAudit.target_tenant_id == target_tenant_id)

    total = (
        await db.execute(select(func.count(SecurityAudit.id)).where(*filters))
    ).scalar() or 0
    rows = (
        await db.execute(
            select(SecurityAudit)
            .where(*filters)
            .order_by(SecurityAudit.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()

    return SecurityAuditListResponse(
        items=[SecurityAuditRead.model_validate(row) for row in rows],
        total=int(total),
    )

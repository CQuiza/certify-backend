"""Panel de administración de tenants (solo superuser, operaciones globales)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db_unscoped
from app.models.user import User
from app.repositories.tenant_repository import tenant_repository
from app.schemas.tenant import (
    AdminPasswordReset,
    TenantCreate,
    TenantCreated,
    TenantRead,
    TenantResetResult,
    TenantStatusUpdate,
)
from app.services.tenant_service import tenant_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin", "tenants"])


def _require_superuser(current: User) -> None:
    if current.role != "superuser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios de plataforma",
        )


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> list:
    _require_superuser(current)
    return await tenant_service.list_tenants(db)


@router.post("", response_model=TenantCreated, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    _require_superuser(current)
    try:
        tenant, admin_password = await tenant_service.create_tenant(
            db,
            name=body.name,
            slug=body.slug,
            admin_email=str(body.admin_email),
            admin_name=body.admin_name,
            admin_password=body.admin_password,
            created_by=current.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    counts = await tenant_service._counts(db, tenant.id)  # noqa: SLF001
    return TenantCreated(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        domain=tenant.domain,
        is_active=bool(tenant.is_active),
        created_at=tenant.created_at.isoformat() if tenant.created_at else None,
        total_users=counts["total_users"],
        total_courses=counts["total_courses"],
        total_certificates=counts["total_certificates"],
        admin_password=admin_password,
    )


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant_status(
    tenant_id: int,
    body: TenantStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    _require_superuser(current)
    tenant = await tenant_service.update_status(
        db, tenant_id, is_active=body.is_active, by=current.id
    )
    counts = await tenant_service._counts(db, tenant.id)  # noqa: SLF001
    return TenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        domain=tenant.domain,
        is_active=bool(tenant.is_active),
        created_at=tenant.created_at.isoformat() if tenant.created_at else None,
        total_users=counts["total_users"],
        total_courses=counts["total_courses"],
        total_certificates=counts["total_certificates"],
    )


@router.post("/{tenant_id}/reset-admin", response_model=TenantResetResult)
async def reset_tenant_admin_password(
    tenant_id: int,
    body: AdminPasswordReset,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Reasigna la contraseña de un administrador del tenant."""
    from app.core.security import generate_secure_password, get_password_hash

    from app.repositories.user_repository import user_repository

    _require_superuser(current)
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")
    admin = await user_repository.get_by_email(db, body.admin_email)
    if admin is None or admin.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Administrador no encontrado en el tenant"
        )
    new_password = generate_secure_password()
    admin.password_hash = get_password_hash(new_password)
    await db.flush()
    logger.info("Contraseña de admin reiniciada — tenant=%s admin=%s by=%s", tenant_id, body.admin_email, current.id)
    return TenantResetResult(
        detail=f"Contraseña reiniciada para {body.admin_email}",
        password=new_password,
    )
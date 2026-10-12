"""Panel de administración de tenants (solo superuser, operaciones globales)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db_unscoped
from app.core.settings import get_settings
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


@router.post("/{tenant_id}/impersonate", status_code=status.HTTP_200_OK)
async def impersonate_tenant(
    tenant_id: int,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """El superuser entra a operar dentro de un tenant sin salir de sesión."""
    _require_superuser(current)
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")
    if not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El tenant está desactivado")

    settings = get_settings()
    resp = JSONResponse(
        content={"detail": "Sesión dirigida al tenant", "tenant_id": tenant.id, "slug": tenant.slug}
    )
    resp.set_cookie(
        key="acting_tenant",
        value=str(tenant.id),
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=8 * 3600,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    logger.info("Superuser %s impersonó tenant %s (%s)", current.email, tenant.id, tenant.slug)
    return resp


@router.post("/stop", status_code=status.HTTP_200_OK)
async def stop_impersonation(
    current: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """Vuelve al tenant de la sesión (limpia la cookie de impersonación)."""
    settings = get_settings()
    resp = JSONResponse(content={"detail": "Volviste a tu tenant"})
    resp.delete_cookie(
        key="acting_tenant",
        httponly=True,
        path="/api/v1",
        domain=settings.cookie_domain,
    )
    return resp


@router.get("/acting")
async def get_acting_tenant(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Devuelve el tenant activo por impersonación (banner del front)."""
    _require_superuser(current)
    acting = request.headers.get("X-Acting-Tenant") or request.cookies.get("acting_tenant")
    if not acting:
        return {"tenant_id": None, "slug": None}
    try:
        tenant_id = int(acting)
    except (TypeError, ValueError):
        return {"tenant_id": None, "slug": None}
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None or not tenant.is_active:
        return {"tenant_id": None, "slug": None}
    return {"tenant_id": tenant.id, "slug": tenant.slug}


@router.get("/{tenant_id}/backup-sql")
async def download_tenant_backup(
    tenant_id: int,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Descarga un backup SQL completo de la base de datos (superuser).

    Es un dump de TODA la base (single-schema multi-tenant). Solo Postgres.
    """
    _require_superuser(current)
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")

    settings = get_settings()
    url = settings.get_database_url()
    if not url.startswith("postgresql") and not url.startswith("postgres"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Backup SQL solo disponible con PostgreSQL",
        )

    host = settings.postgres_host or settings.postgres_host
    port = settings.postgres_port or 5432
    user = settings.postgres_user
    password = settings.postgres_password
    database = settings.postgres_db
    if not (user and database):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credenciales de PostgreSQL incompletas en el entorno",
        )

    import asyncio
    import os
    import subprocess

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        "-h", str(host),
        "-p", str(port),
        "-U", str(user),
        "-d", str(database),
        "--no-owner",
        "--no-privileges",
    ]

    def _run() -> bytes:
        result = subprocess.run(cmd, env=env, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.decode("utf-8", errors="replace")[:500]
            )
        return result.stdout

    try:
        data = await asyncio.to_thread(_run)
    except Exception as exc:
        logger.exception("pg_dump falló — tenant=%s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falló el backup: {exc}",
        ) from exc

    from datetime import datetime, timezone

    from urllib.parse import quote

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{database}_{now}.sql"
    logger.info("Backup SQL descargado — tenant=%s by=%s size=%s", tenant_id, current.email, len(data))
    return StreamingResponse(
        iter([data]),
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename*=UTF-8\'\'{quote(filename)}'},
    )
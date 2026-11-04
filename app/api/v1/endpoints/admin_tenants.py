"""Panel de administración de tenants (solo superuser, operaciones globales)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
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
from app.schemas.tenant_payment import (
    TenantPaymentCreate,
    TenantPaymentRead,
    TenantPaymentUpdate,
)
from app.services import refresh_session_service, security_audit_service
from app.services.tenant_billing_service import tenant_billing_service
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
    tenants = await tenant_service.list_tenants(db)
    summaries = await tenant_billing_service.summaries(
        db, [(t["id"], t["slug"]) for t in tenants]
    )
    for tenant in tenants:
        tenant["billing"] = summaries.get(tenant["id"])
    return tenants


@router.post("", response_model=TenantCreated, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    request: Request,
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
    await security_audit_service.record(
        db,
        actor=current,
        action="tenant_created",
        target_tenant_id=tenant.id,
        target_type="tenant",
        target_id=tenant.id,
        after={"name": tenant.name, "slug": tenant.slug},
        request=request,
    )
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
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    _require_superuser(current)
    before = await tenant_repository.get_by_id(db, tenant_id)
    tenant = await tenant_service.update_status(
        db, tenant_id, is_active=body.is_active, by=current.id
    )
    await security_audit_service.record(
        db,
        actor=current,
        action="tenant_status_changed",
        target_tenant_id=tenant.id,
        target_type="tenant",
        target_id=tenant.id,
        before={"is_active": bool(before.is_active) if before else None},
        after={"is_active": bool(tenant.is_active)},
        request=request,
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
    request: Request,
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
    await refresh_session_service.revoke_all_for_user(
        db, admin.id, reason="admin_password_reset"
    )
    await security_audit_service.record(
        db,
        actor=current,
        action="admin_password_reset",
        target_tenant_id=tenant_id,
        target_type="user",
        target_id=admin.id,
        after={"email": admin.email},
        request=request,
    )
    logger.info("Contraseña de admin reiniciada — tenant=%s admin=%s by=%s", tenant_id, body.admin_email, current.id)
    return TenantResetResult(
        detail=f"Contraseña reiniciada para {body.admin_email}",
        password=new_password,
    )


def _payment_snapshot(payment) -> dict:
    """Resumen serializable para la auditoría."""
    return {
        "plan": payment.plan,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "period_start": payment.period_start.isoformat(),
        "period_end": payment.period_end.isoformat(),
        "paid_at": payment.paid_at.isoformat(),
        "reference": payment.reference,
    }


@router.get("/{tenant_id}/payments", response_model=list[TenantPaymentRead])
async def list_tenant_payments(
    tenant_id: int,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> list:
    """Historial de pagos del tenant (solo superuser)."""
    _require_superuser(current)
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")
    return await tenant_billing_service.list_payments(db, tenant_id)


@router.post(
    "/{tenant_id}/payments",
    response_model=TenantPaymentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_payment(
    tenant_id: int,
    body: TenantPaymentCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Registra un pago recibido y la cobertura que otorga."""
    _require_superuser(current)
    tenant = await tenant_repository.get_by_id(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")

    payment = await tenant_billing_service.create_payment(
        db, tenant_id=tenant.id, data=body, created_by=current.id
    )
    await security_audit_service.record(
        db,
        actor=current,
        action="tenant_payment_created",
        target_tenant_id=tenant.id,
        target_type="tenant_payment",
        target_id=payment.id,
        after=_payment_snapshot(payment),
        request=request,
    )
    return payment


@router.patch("/{tenant_id}/payments/{payment_id}", response_model=TenantPaymentRead)
async def update_tenant_payment(
    tenant_id: int,
    payment_id: int,
    body: TenantPaymentUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Corrige un pago; si cambia el plan o el inicio, recalcula la cobertura."""
    _require_superuser(current)
    payment = await tenant_billing_service.get_payment(db, tenant_id, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado"
        )
    before = _payment_snapshot(payment)
    payment = await tenant_billing_service.update_payment(db, payment, body)
    await security_audit_service.record(
        db,
        actor=current,
        action="tenant_payment_updated",
        target_tenant_id=tenant_id,
        target_type="tenant_payment",
        target_id=payment.id,
        before=before,
        after=_payment_snapshot(payment),
        request=request,
    )
    return payment


@router.delete("/{tenant_id}/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_payment(
    tenant_id: int,
    payment_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> None:
    """Elimina un pago cargado por error (queda auditado)."""
    _require_superuser(current)
    payment = await tenant_billing_service.get_payment(db, tenant_id, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado"
        )
    before = _payment_snapshot(payment)
    await tenant_billing_service.delete_payment(db, payment)
    await security_audit_service.record(
        db,
        actor=current,
        action="tenant_payment_deleted",
        target_tenant_id=tenant_id,
        target_type="tenant_payment",
        target_id=payment_id,
        before=before,
        request=request,
    )


@router.post("/{tenant_id}/impersonate", status_code=status.HTTP_200_OK)
async def impersonate_tenant(
    tenant_id: int,
    request: Request,
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
    await security_audit_service.record(
        db,
        actor=current,
        action="impersonation_started",
        target_tenant_id=tenant.id,
        target_type="tenant",
        target_id=tenant.id,
        after={"slug": tenant.slug},
        request=request,
    )
    logger.info("Superuser %s impersonó tenant %s (%s)", current.email, tenant.id, tenant.slug)
    return resp


@router.post("/stop", status_code=status.HTTP_200_OK)
async def stop_impersonation(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """Vuelve al tenant de la sesión (limpia la cookie de impersonación)."""
    acting = request.headers.get("X-Acting-Tenant") or request.cookies.get("acting_tenant")
    target_tenant_id = None
    if acting:
        try:
            target_tenant_id = int(acting)
        except (TypeError, ValueError):
            target_tenant_id = None
    if target_tenant_id is not None:
        await security_audit_service.record(
            db,
            actor=current,
            action="impersonation_stopped",
            target_tenant_id=target_tenant_id,
            target_type="tenant",
            target_id=target_tenant_id,
            request=request,
        )
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

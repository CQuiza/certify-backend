"""Dashboard — estadísticas globales."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.dashboard_repository import dashboard_repository
from app.repositories.user_repository import user_repository
from app.schemas.dashboard import AdminRead, DashboardStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def require_teacher_or_staff(current: User) -> User:
    if current.role not in (
        UserRole.superuser.value,
        UserRole.admin.value,
        UserRole.teacher.value,
    ):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo personal autorizado puede acceder al dashboard",
        )
    return current


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> DashboardStatsResponse:
    require_teacher_or_staff(current)
    logger.info("Solicitando stats del dashboard — by=%s", current.email)
    return await dashboard_repository.get_stats(db)


@router.get("/admins", response_model=list[AdminRead])
async def list_dashboard_admins(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> list:
    """Relación de administradores del tenant (id, nombres, documento, correo, teléfono)."""
    if current.role not in (UserRole.superuser.value, UserRole.admin.value):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios y administradores",
        )
    rows = await user_repository.list_admins(db)
    logger.info("Solicitando admins del dashboard — by=%s", current.email)
    return list(rows)

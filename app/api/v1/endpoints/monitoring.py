"""Monitorización: registro y consulta de logs/errores."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db_unscoped
from app.models.user import User
from app.repositories.system_log_repository import system_log_repository
from app.schemas.system_log import SystemLogListResponse, SystemLogRead

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/logs", response_model=SystemLogListResponse)
async def list_system_logs(
    db: Annotated[AsyncSession, Depends(get_db_unscoped)],
    current: Annotated[User, Depends(get_current_user)],
    level: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SystemLogListResponse:
    """Lista los logs registrados. Solo superusuario."""
    if current.role != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo superusuario")
    total = await system_log_repository.count(db, level=level, source=source, search=search)
    rows = await system_log_repository.list(
        db, level=level, source=source, search=search, skip=skip, limit=limit
    )
    return SystemLogListResponse(items=[SystemLogRead.model_validate(r) for r in rows], total=total)

"""Monitorización: registro y consulta de logs/errores."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_optional_user
from app.core.database import get_db, get_db_unscoped
from app.core.rate_limit import limiter
from app.models.user import User
from app.repositories.system_log_repository import system_log_repository
from app.schemas.system_log import SystemLogCreate, SystemLogListResponse, SystemLogRead

logger = logging.getLogger(__name__)

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


@router.post("/logs", response_model=SystemLogRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_system_log(
    request: Request,
    body: SystemLogCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User | None, Depends(get_optional_user)],
) -> SystemLogRead:
    """Registra un log/error reportado por el cliente (frontend)."""
    row = await system_log_repository.create(
        db,
        level=body.level,
        source=body.source,
        event=body.event,
        detail=body.detail,
        stacktrace=body.stacktrace,
        request_id=request.headers.get("x-request-id"),
        path=body.path,
        method=None,
        status_code=None,
        user_id=current.id if current else None,
    )
    return SystemLogRead.model_validate(row)

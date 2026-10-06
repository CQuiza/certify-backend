"""Servicio para registrar logs/errores de la plataforma.

Usa su propia sesión para poder invocarse desde middleware y manejadores de
excepciones (donde la sesión de request puede estar comprometida). Nunca
propaga errores: registrar un log no debe tumbar la petición.
"""

from __future__ import annotations

import logging

from app.core.database import AsyncSessionLocal
from app.repositories.system_log_repository import system_log_repository

logger = logging.getLogger(__name__)


async def write_system_log(
    *,
    level: str,
    source: str,
    event: str,
    detail: str | None = None,
    stacktrace: str | None = None,
    request_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    user_id: int | None = None,
) -> None:
    """Persiste un evento en ``system_logs``. Silencioso ante fallos."""
    try:
        async with AsyncSessionLocal() as session:
            await system_log_repository.create(
                session,
                level=level,
                source=source,
                event=(event or "unknown")[:255],
                detail=detail,
                stacktrace=stacktrace,
                request_id=request_id,
                path=path,
                method=method,
                status_code=status_code,
                user_id=user_id,
            )
            await session.commit()
    except Exception:
        logger.exception("No se pudo persistir el system_log — event=%s", event)
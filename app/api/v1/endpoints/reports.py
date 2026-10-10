"""Reportes analíticos (solo superuser/admin)."""

import csv
import io
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.report_service import REPORTS, catalog, parse_range

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_admin(current: User) -> None:
    if current.role not in ("superuser", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios y administradores pueden generar reportes",
        )


@router.get("")
async def list_reports(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> list:
    _require_admin(current)
    return catalog()


@router.get("/{report_key}")
async def run_report(
    report_key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
    format: Annotated[str, Query()] = "json",
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
):
    _require_admin(current)
    meta = REPORTS.get(report_key)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reporte no encontrado")

    try:
        start, end = parse_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fechas inválidas (formato YYYY-MM-DD)",
        ) from exc
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha inicial no puede ser mayor que la final")

    rows = await meta["fn"](db, start, end, limit)
    columns = meta["columns"]

    if format.lower() == "csv":
        return _csv_response(report_key, columns, rows)

    return {
        "key": report_key,
        "title": meta["title"],
        "columns": columns,
        "rows": rows,
    }


def _csv_response(report_key: str, columns: list[dict], rows: list[dict]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([c["label"] for c in columns])
    keys = [c["key"] for c in columns]
    for row in rows:
        writer.writerow([row.get(k) if row.get(k) is not None else "" for k in keys])
    data = "\ufeff" + buffer.getvalue()  # BOM para Excel
    return Response(
        content=data.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_key}.csv"'},
    )
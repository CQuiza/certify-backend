"""Entregas de tareas por estudiantes."""

import asyncio
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.course import CourseEnrollment
from app.models.lesson import Lesson
from app.models.lesson_task import LessonTask
from app.models.user import User
from app.repositories.lesson_task_repository import lesson_task_repository
from app.repositories.module_repository import module_repository
from app.repositories.task_submission_repository import task_submission_repository
from app.schemas.task_submission import TaskSubmissionRead, TaskSubmissionWithUserRead
from app.services.access import is_super_or_admin, is_teacher, require_course_visible
from app.utils.minio_client import get_minio_client

router = APIRouter(tags=["task-submissions"])


async def _assert_enrolled_in_task_course(
    db: AsyncSession, current: User, task: LessonTask
) -> None:
    """Verifica que el usuario esté inscrito en el curso de la tarea (o sea staff/teacher)."""
    if is_super_or_admin(current) or is_teacher(current):
        return
    lesson = await db.execute(select(Lesson).where(Lesson.id == task.lesson_id))
    lesson = lesson.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada")
    mod = await module_repository.get_by_id(db, lesson.module_id)
    if not mod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Módulo no encontrado")
    r = await db.execute(
        select(CourseEnrollment).where(
            CourseEnrollment.course_id == mod.course_id,
            CourseEnrollment.user_id == current.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No estás inscrito en este curso",
        )


def _sanitize_filename(identity_number: str, task_title: str) -> str:
    title = re.sub(r"[^\w\s]", "", task_title).strip().replace(" ", "_")
    return f"{identity_number}_{title}.pdf"


@router.post(
    "/tasks/{task_id}/submit",
    response_model=TaskSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_task(
    task_id: int,
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    if current.role not in ("superuser", "admin", "teacher", "student"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso"
        )

    task = await lesson_task_repository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada"
        )

    await _assert_enrolled_in_task_course(db, current, task)

    # Validar extensión .pdf
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos PDF",
        )

    # Validar tamaño
    settings = get_settings()
    max_size = settings.task_max_upload_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera el límite de {settings.task_max_upload_size_mb} MB",
        )

    # Verificar unique (task_id, user_id)
    existing = await task_submission_repository.get_by_task_and_user(
        db, task_id, current.id
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya has entregado esta tarea. Solo se permite un intento.",
        )

    original_filename = _sanitize_filename(
        current.identity_number, task.title
    )
    object_name = (
        f"{settings.minio_path_task_submissions}/{task_id}/{current.id}.pdf"
    )

    try:
        client = get_minio_client(settings)
        client.ensure_bucket()
        await asyncio.to_thread(
            client.upload_bytes,
            object_name,
            data,
            content_type="application/pdf",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al subir archivo: {e}",
        )

    return await task_submission_repository.create(
        db,
        task_id=task_id,
        user_id=current.id,
        file_url=object_name,
        original_filename=original_filename,
        mime_type="application/pdf",
    )


@router.get(
    "/tasks/{task_id}/submissions",
    response_model=list[TaskSubmissionWithUserRead],
)
async def list_submissions(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    task = await lesson_task_repository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada"
        )
    await _assert_enrolled_in_task_course(db, current, task)

    if not (is_super_or_admin(current) or is_teacher(current)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores y profesores pueden ver todas las entregas",
        )

    rows = await task_submission_repository.list_by_task(db, task_id)
    result = []
    for s in rows:
        result.append(
            TaskSubmissionWithUserRead(
                id=s.id,
                task_id=s.task_id,
                user_id=s.user_id,
                file_url=s.file_url,
                original_filename=s.original_filename,
                mime_type=s.mime_type,
                submitted_at=s.submitted_at,
                user_name=s.user.name,
                user_email=s.user.email,
            )
        )
    return result


@router.get("/tasks/{task_id}/my-submission")
async def get_my_submission(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> TaskSubmissionRead | None:
    sub = await task_submission_repository.get_by_task_and_user(
        db, task_id, current.id
    )
    return sub


@router.get("/submissions/{submission_id}/file")
async def download_submission_file(
    submission_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> Response:
    sub = await task_submission_repository.get_by_id(db, submission_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entrega no encontrada"
        )

    if current.id != sub.user_id and not (
        is_super_or_admin(current) or is_teacher(current)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para descargar esta entrega",
        )

    settings = get_settings()
    try:
        client = get_minio_client(settings)
        data = await asyncio.to_thread(client.download_bytes, sub.file_url)
    except S3Error as e:
        code = str(getattr(e, "code", "") or "").lower()
        if code in ("nosuchkey", "notfound"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Archivo no encontrado",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    from urllib.parse import quote

    encoded = quote(sub.original_filename)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )

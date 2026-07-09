"""Archivos de lecciones."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.enums import UserRole
from app.models.lesson import Lesson
from app.models.user import User
from app.repositories.lesson_file_repository import lesson_file_repository
from app.repositories.lesson_repository import lesson_repository
from app.repositories.module_repository import module_repository
from app.schemas.lesson_file import LessonFileCreate, LessonFileRead
from app.services.access import is_super_or_admin, is_teacher, teacher_owns_module
from app.utils.minio_client import get_minio_client

router = APIRouter(prefix="/lessons", tags=["lesson_files"])

_ALLOWED_EXTENSIONS = {"jpg", "png", "pdf", "docx", "pptx", "xlsx"}


def _validate_file_extension(filename: str) -> None:
    if "." not in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo debe tener una extensión",
        )
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensión .{ext} no permitida. Extensiones aceptadas: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )


async def _assert_can_manage(
    db: AsyncSession,
    current: User,
    lesson: Lesson,
) -> None:
    if current.role in (UserRole.superuser.value, UserRole.admin.value):
        return
    if is_teacher(current):
        mod = await module_repository.get_by_id(db, lesson.module_id)
        if mod and await teacher_owns_module(db, current, mod):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Sin permiso para gestionar archivos",
    )


@router.get("/{lesson_id}/files", response_model=list[LessonFileRead])
async def list_lesson_files(
    lesson_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list:
    lesson = await lesson_repository.get_by_id(db, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada"
        )
    mod = await module_repository.get_by_id(db, lesson.module_id)
    if mod:
        from app.services.access import require_course_visible
        await require_course_visible(db, current, mod.course_id, need_content=True)
    rows = await lesson_file_repository.list_by_lesson(
        db, lesson_id, skip=skip, limit=limit
    )
    return list(rows)


@router.post("/{lesson_id}/files", response_model=LessonFileRead, status_code=status.HTTP_201_CREATED)
async def create_lesson_file(
    lesson_id: int,
    body: LessonFileCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    lesson = await lesson_repository.get_by_id(db, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada"
        )
    await _assert_can_manage(db, current, lesson)
    return await lesson_file_repository.create(
        db,
        lesson_id=lesson_id,
        original_filename=body.original_filename,
        mime_type=body.mime_type,
        order_index=body.order_index,
    )


@router.delete("/{lesson_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson_file(
    lesson_id: int,
    file_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> None:
    lesson = await lesson_repository.get_by_id(db, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada"
        )
    await _assert_can_manage(db, current, lesson)
    lesson_file = await lesson_file_repository.get_by_id(db, file_id)
    if not lesson_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archivo no encontrado"
        )
    if lesson_file.file_url:
        settings = get_settings()
        try:
            client = get_minio_client(settings)
            await asyncio.to_thread(client.remove_object, lesson_file.file_url)
        except Exception:
            pass
    await lesson_file_repository.delete(db, lesson_file)


@router.post("/{lesson_id}/files/{file_id}/upload", response_model=LessonFileRead)
async def upload_lesson_file(
    lesson_id: int,
    file_id: int,
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    lesson = await lesson_repository.get_by_id(db, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada"
        )
    await _assert_can_manage(db, current, lesson)
    lesson_file = await lesson_file_repository.get_by_id(db, file_id)
    if not lesson_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archivo no encontrado"
        )

    original_filename = file.filename or f"lesson-file-{file_id}"
    _validate_file_extension(original_filename)

    settings = get_settings()
    max_size = settings.lesson_file_max_upload_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera el límite de {settings.lesson_file_max_upload_size_mb} MB",
        )
    ext = ""
    if original_filename and "." in original_filename:
        ext = original_filename.rsplit(".", 1)[-1]
    object_name = f"{settings.minio_path_lesson_files}/{lesson_id}/{file_id}.{ext}"

    try:
        client = get_minio_client(settings)
        client.ensure_bucket()
        await asyncio.to_thread(
            client.upload_bytes,
            object_name,
            data,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al subir archivo: {e}",
        )

    return await lesson_file_repository.update(
        db,
        lesson_file,
        {
            "file_url": object_name,
            "original_filename": original_filename,
            "mime_type": file.content_type,
        },
    )


@router.get("/{lesson_id}/files/{file_id}/file")
async def download_lesson_file(
    lesson_id: int,
    file_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    download: Annotated[bool, Query()] = False,
) -> Response:
    lesson = await lesson_repository.get_by_id(db, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lección no encontrada"
        )
    mod = await module_repository.get_by_id(db, lesson.module_id)
    if mod:
        from app.services.access import require_course_visible
        await require_course_visible(db, current, mod.course_id, need_content=True)

    lesson_file = await lesson_file_repository.get_by_id(db, file_id)
    if not lesson_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archivo no encontrado"
        )
    if not lesson_file.file_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este archivo no tiene contenido subido",
        )

    settings = get_settings()
    try:
        client = get_minio_client(settings)
        data = await asyncio.to_thread(client.download_bytes, lesson_file.file_url)
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

    disposition = "inline" if not download else "attachment"
    filename = lesson_file.original_filename or (
        lesson_file.file_url.rsplit("/", 1)[-1] if "/" in lesson_file.file_url else "file"
    )
    media_type = lesson_file.mime_type or "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
        },
    )

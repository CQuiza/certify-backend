"""Cursos."""

import asyncio
import logging
from io import BytesIO
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from minio.error import S3Error
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.course import Course
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.course_repository import course_repository
from app.schemas.course import CourseCreate, CoursePublicRead, CourseRead, CourseUpdate
from app.services.access import is_super_or_admin, is_student, require_course_visible
from app.services.course_service import course_service
from app.utils.minio_client import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/courses", tags=["courses"])

_MAX_COURSE_IMAGE_BYTES = 5 * 1024 * 1024
_COURSE_IMAGE_MAX_WIDTH = 1200


def _assert_can_manage_course(current: User, course: Course) -> None:
    """Docente dueño del curso o admin/superuser."""
    if current.role == UserRole.teacher.value:
        if course.teacher_id != current.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el docente del curso puede gestionar su imagen",
            )
    elif not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores")


@router.get("")
async def list_courses(
    db: Annotated[AsyncSession, Depends(get_db)],
    optional_user: Annotated[User | None, Depends(get_optional_user)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=10000)] = 5000,
    search: Annotated[str | None, Query()] = None,
    catalog: Annotated[bool, Query()] = False,
) -> list:
    rows = await course_service.list_for_actor(
        db, actor=optional_user, skip=skip, limit=limit, search=search, catalog=catalog
    )
    if optional_user and is_super_or_admin(optional_user):
        return [CourseRead.model_validate(r).model_dump() for r in rows]
    return [CoursePublicRead.model_validate(r).model_dump() for r in rows]


@router.get("/{course_id}", response_model=CourseRead)
async def get_course(
    course_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    optional_user: Annotated[User | None, Depends(get_optional_user)],
) -> object:
    need_enrollment = optional_user is not None and is_student(optional_user)
    await require_course_visible(db, optional_user, course_id, need_content=need_enrollment)
    c = await course_repository.get_by_id(db, course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
    return c


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    if current.role == UserRole.teacher.value:
        # El teacher crea el curso y queda como su docente.
        return await course_repository.create(
            db,
            title=body.title,
            description=body.description,
            certificate_type_id=body.certificate_type_id,
            teacher_id=current.id,
            status=body.status.value,
            price=body.price,
            renewal_price=body.renewal_price,
            is_for_sale=body.is_for_sale,
        )
    if not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores o docentes")
    return await course_repository.create(
        db,
        title=body.title,
        description=body.description,
        certificate_type_id=body.certificate_type_id,
        teacher_id=body.teacher_id,
        status=body.status.value,
        price=body.price,
        renewal_price=body.renewal_price,
        is_for_sale=body.is_for_sale,
    )


@router.patch("/{course_id}", response_model=CourseRead)
async def update_course(
    course_id: int,
    body: CourseUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    c = await course_repository.get_by_id(db, course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
    if current.role == UserRole.teacher.value:
        if c.teacher_id != current.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el docente del curso puede editarlo")
    elif not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores")
    payload = body.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] is not None:
        payload["status"] = payload["status"].value
    return await course_repository.update(db, c, payload)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> None:
    c = await course_repository.get_by_id(db, course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
    if current.role == UserRole.teacher.value:
        if c.teacher_id != current.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el docente del curso puede eliminarlo")
    elif not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores")
    await course_repository.delete(db, c)


# ── Imagen descriptiva del curso ─────────────────────────────────────────────


@router.post("/{course_id}/image", response_model=CourseRead)
async def upload_course_image(
    course_id: int,
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    """Sube/reemplaza la imagen del curso (WebP, redimensionada)."""
    c = await course_repository.get_by_id(db, course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
    _assert_can_manage_course(current, c)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío")
    if len(data) > _MAX_COURSE_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen supera el límite de 5 MB",
        )
    try:
        img = Image.open(BytesIO(data))
        img.verify()
        img = Image.open(BytesIO(data))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es una imagen válida",
        ) from exc

    img = img.convert("RGB")
    img.thumbnail((_COURSE_IMAGE_MAX_WIDTH, _COURSE_IMAGE_MAX_WIDTH))
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=85)

    settings = get_settings()
    object_key = f"{settings.minio_path_course_images}/{course_id}/{uuid4().hex}.webp"
    old_key = c.image_object_key
    try:
        client = get_minio_client(settings)
        client.ensure_bucket()
        await asyncio.to_thread(
            client.upload_bytes, object_key, buf.getvalue(), content_type="image/webp"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo guardar la imagen: {e}",
        ) from e

    updated = await course_repository.update(db, c, {"image_object_key": object_key})
    if old_key and old_key != object_key:
        try:
            await asyncio.to_thread(get_minio_client(settings).remove_object, old_key)
        except Exception:
            logger.warning("No se pudo eliminar la imagen anterior del curso %s", course_id)
    logger.info("Imagen de curso actualizada — course_id=%s, by=%s", course_id, current.email)
    return updated


@router.delete("/{course_id}/image", status_code=status.HTTP_200_OK)
async def delete_course_image(
    course_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Elimina la imagen del curso."""
    c = await course_repository.get_by_id(db, course_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curso no encontrado")
    _assert_can_manage_course(current, c)

    if c.image_object_key:
        try:
            await asyncio.to_thread(
                get_minio_client(get_settings()).remove_object, c.image_object_key
            )
        except Exception:
            logger.warning("No se pudo eliminar la imagen del curso %s", course_id)
    await course_repository.update(db, c, {"image_object_key": None})
    return {"detail": "Imagen eliminada"}


@router.get("/{course_id}/image")
async def get_course_image(
    course_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Sirve la imagen del curso (pública, para el catálogo)."""
    c = await course_repository.get_by_id(db, course_id)
    if not c or not c.image_object_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="El curso no tiene imagen"
        )

    settings = get_settings()
    if settings.media_public_base_url:
        base = settings.media_public_base_url.rstrip("/")
        return RedirectResponse(
            f"{base}/{c.image_object_key}", status_code=status.HTTP_302_FOUND
        )

    try:
        data = await asyncio.to_thread(
            get_minio_client(settings).download_bytes, c.image_object_key
        )
    except S3Error as e:
        code = str(getattr(e, "code", "") or "").lower()
        if code in ("nosuchkey", "notfound"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada"
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    return Response(
        content=data,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=300",
            "ETag": f'"{c.image_object_key}"',
        },
    )

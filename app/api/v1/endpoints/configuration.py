"""Configuración de plataforma (solo superuser)."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.user import User
from app.services.certificate_pdf import (
    _resolve_under_app,
    resolve_certificate_template,
)
from app.utils.minio_client import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/configuration", tags=["configuration"])

_TEMPLATE_OBJECT_NAME = "certificate_template.pdf"
_MAX_TEMPLATE_SIZE = 10 * 1024 * 1024  # 10 MB


def _require_superuser(current: User) -> None:
    if current.role != "superuser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios pueden acceder a la configuración",
        )


def _template_object_name(settings) -> str:
    prefix = settings.minio_path_certificate_template.strip().strip("/")
    return f"{prefix}/{_TEMPLATE_OBJECT_NAME}" if prefix else _TEMPLATE_OBJECT_NAME


@router.get("/certificate-template")
async def get_certificate_template_info(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Devuelve si hay una plantilla custom y sus metadatos."""
    _require_superuser(current)
    settings = get_settings()

    if settings.minio_access_key and settings.minio_secret_key:
        try:
            client = get_minio_client(settings)
            stat = client.client.stat_object(
                client.bucket, _template_object_name(settings)
            )
            return {
                "is_custom": True,
                "filename": _TEMPLATE_OBJECT_NAME,
                "size_bytes": stat.size,
                "updated_at": (
                    stat.last_modified.isoformat()
                    if isinstance(stat.last_modified, datetime)
                    else None
                ),
            }
        except S3Error as e:
            if e.code not in ("NoSuchKey", "NotFound"):
                logger.warning("Error stat plantilla custom — %s", e)
        except Exception:
            logger.exception("Error consultando plantilla custom en MinIO")

    default = _resolve_under_app(settings.certificate_template_pdf)
    return {
        "is_custom": False,
        "filename": default.name,
        "size_bytes": default.stat().st_size if default.is_file() else None,
        "updated_at": None,
    }


@router.get("/certificate-template/preview")
async def preview_certificate_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Sirve la plantilla del certificado EN USO (exacta, sin overlay).

    Permite al superusuario ver/descargar el fichero que se está usando
    antes de subir uno nuevo."""
    _require_superuser(current)
    settings = get_settings()

    template = resolve_certificate_template(settings)
    if isinstance(template, bytes):
        data = template
    else:
        if not template.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No existe la plantilla por defecto",
            )
        data = template.read_bytes()

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{_TEMPLATE_OBJECT_NAME}"',
        },
    )


@router.post("/certificate-template")
async def upload_certificate_template(
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Sube una nueva plantilla PDF de certificado (reemplaza la custom)."""
    _require_superuser(current)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos PDF",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío",
        )
    if len(data) > _MAX_TEMPLATE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera el límite de {_MAX_TEMPLATE_SIZE // (1024 * 1024)} MB",
        )
    if not data.lstrip().startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es un PDF válido",
        )

    settings = get_settings()
    try:
        client = get_minio_client(settings)
        client.ensure_bucket()
        client.upload_bytes(
            _template_object_name(settings),
            data,
            content_type="application/pdf",
        )
    except Exception as e:
        logger.exception("Error subiendo plantilla de certificado")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al guardar la plantilla: {e}",
        )

    logger.info("Plantilla de certificado actualizada por %s", current.email)
    return {"detail": "Plantilla de certificado actualizada correctamente"}


@router.delete("/certificate-template")
async def restore_default_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Elimina la plantilla custom; se vuelve a usar la por defecto."""
    _require_superuser(current)
    settings = get_settings()

    if not (settings.minio_access_key and settings.minio_secret_key):
        return {"detail": "Ya se usa la plantilla por defecto"}

    try:
        client = get_minio_client(settings)
        client.remove_object(_template_object_name(settings))
    except Exception:
        logger.exception("Error eliminando plantilla custom de MinIO")

    logger.info("Plantilla de certificado restaurada a la default por %s", current.email)
    return {"detail": "Se restauró la plantilla por defecto"}
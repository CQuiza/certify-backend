"""Configuración de plataforma (solo superuser para escritura).

Marca/organización, SMTP y plantillas de correo, más la plantilla de
certificado (patrón existente). La lectura de marca (branding) está reservada
a usuarios autenticados: las páginas públicas conservan la marca por defecto
de Certify.
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from minio.error import S3Error
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.settings import get_settings
from app.models.enums import EmailTemplateKind
from app.models.user import User
from app.schemas.platform_settings import (
    BrandingRead,
    EmailSettingsRead,
    EmailSettingsUpdate,
    EmailTemplateRead,
    EmailTemplateUpdate,
    EmailTemplatesListRead,
    OrganizationUpdate,
    TestEmailRequest,
)
from app.services.email_template_service import get_placeholders
from app.services.platform_settings_service import platform_settings_service
from app.services.certificate_pdf import _resolve_under_app, resolve_certificate_template
from app.utils.email import send_test_email
from app.utils.minio_client import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/configuration", tags=["configuration"])

_TEMPLATE_OBJECT_NAME = "certificate_template.pdf"
_MAX_TEMPLATE_SIZE = 10 * 1024 * 1024  # 10 MB
_MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


def _require_superuser(current: User) -> None:
    if current.role != "superuser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo superusuarios pueden acceder a la configuración",
        )


def _require_template_kind(kind: str) -> str:
    if kind not in {k.value for k in EmailTemplateKind}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de plantilla inválido",
        )
    return kind


def _template_object_name(settings) -> str:
    prefix = settings.minio_path_certificate_template.strip().strip("/")
    return f"{prefix}/{_TEMPLATE_OBJECT_NAME}" if prefix else _TEMPLATE_OBJECT_NAME


# ── Marca / organización (lectura autenticada, escritura superuser) ─────────


@router.get("/branding", response_model=BrandingRead)
async def get_branding(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Marca visible para usuarios autenticados (dashboard, sidebar)."""
    return await platform_settings_service.get_branding(db)


@router.get("/branding/logo")
async def get_branding_logo(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Sirve el logo personalizado (solo autenticado). 404 si no hay custom."""
    settings = get_settings()
    if not (settings.minio_access_key and settings.minio_secret_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sin logo")

    data = await platform_settings_service.get_logo_bytes()
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sin logo")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.put("/organization", response_model=BrandingRead)
async def update_organization(
    body: OrganizationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Actualiza nombre de organización y mensaje del dashboard."""
    _require_superuser(current)
    return await platform_settings_service.save_organization(
        db,
        organization_name=body.organization_name,
        dashboard_message=body.dashboard_message,
        updated_by=current.id,
    )


# ── Correo saliente / SMTP ──────────────────────────────────────────────────


@router.get("/email", response_model=EmailSettingsRead)
async def get_email_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Devuelve la configuración SMTP (la contraseña nunca se expone)."""
    _require_superuser(current)
    return await platform_settings_service.get_email_settings(db)


@router.put("/email", response_model=EmailSettingsRead)
async def update_email_settings(
    body: EmailSettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Guarda la configuración SMTP (contraseña cifrada en BD)."""
    _require_superuser(current)
    return await platform_settings_service.save_email_settings(
        db,
        smtp_enabled=body.smtp_enabled,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_user=body.smtp_user,
        smtp_password=body.smtp_password,
        clear_smtp_password=body.clear_smtp_password,
        smtp_tls=body.smtp_tls,
        email_from=body.email_from,
        email_from_name=body.email_from_name,
        updated_by=current.id,
    )


@router.post("/email/test", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def send_test_email_endpoint(
    request: Request,
    body: TestEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Envía un correo de prueba con la configuración SMTP efectiva."""
    _require_superuser(current)
    try:
        await send_test_email(str(body.email_to))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo enviar el correo de prueba: {e}",
        ) from e
    return {"detail": "Correo de prueba enviado"}


@router.post("/email/logo", status_code=status.HTTP_200_OK)
async def upload_branding_logo(
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Sube el logo de la organización (PNG/JPG/WebP). Se normaliza a PNG."""
    _require_superuser(current)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío")
    if len(data) > _MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_TOO_LARGE,
            detail="El logo supera 2 MB",
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

    img = img.convert("RGBA")
    img.thumbnail((512, 512))
    buf = BytesIO()
    img.save(buf, format="PNG")
    try:
        await platform_settings_service.save_logo(db, buf.getvalue(), updated_by=current.id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    logger.info("Logo de marca actualizado por %s", current.email)
    return {"detail": "Logo actualizado correctamente"}


@router.delete("/email/logo", status_code=status.HTTP_200_OK)
async def restore_branding_logo(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Elimina el logo personalizado; se vuelve a la marca por defecto."""
    _require_superuser(current)
    await platform_settings_service.remove_logo(db, updated_by=current.id)
    return {"detail": "Se restauró la marca por defecto"}


# ── Plantillas de correo ────────────────────────────────────────────────────


@router.get("/email/templates", response_model=EmailTemplatesListRead)
async def list_email_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Lista plantillas efectivas y placeholders disponibles."""
    _require_superuser(current)
    items = await platform_settings_service.list_email_templates(db)
    return {
        "items": items,
        "placeholders": get_placeholders(),
    }


@router.get("/email/templates/{kind}", response_model=EmailTemplateRead)
async def get_email_template(
    kind: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    _require_superuser(current)
    _require_template_kind(kind)
    return await platform_settings_service.get_email_template(db, kind)


@router.put("/email/templates/{kind}", response_model=EmailTemplateRead)
async def update_email_template(
    kind: str,
    body: EmailTemplateUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Guarda asunto/cuerpo de una plantilla de correo."""
    _require_superuser(current)
    _require_template_kind(kind)
    return await platform_settings_service.save_email_template(
        db,
        kind=kind,
        subject=body.subject,
        body_html=body.body_html,
        is_enabled=body.is_enabled,
        updated_by=current.id,
    )


@router.delete("/email/templates/{kind}", response_model=EmailTemplateRead)
async def restore_email_template(
    kind: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Restaura una plantilla a su default."""
    _require_superuser(current)
    _require_template_kind(kind)
    return await platform_settings_service.restore_email_template(
        db, kind, updated_by=current.id
    )


# ── Plantilla de certificado (patrón existente) ─────────────────────────────


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
    """Sirve la plantilla del certificado EN USO (exacta, sin overlay)."""
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
            status_code=status.HTTP_413_REQUEST_TOO_LARGE,
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
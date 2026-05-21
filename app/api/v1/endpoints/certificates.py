"""Certificados emitidos."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.certificate_repository import certificate_repository
from app.schemas.certificate import (
    CertificateIssueRequest,
    CertificateRead,
    CertificateUpdate,
)
from app.services.access import is_super_or_admin
from app.services.certificate_service import (
    _minio_object_key,
    _require_minio,
    certificate_service,
)
from app.utils.minio_client import get_minio_client

router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.get("", response_model=list[CertificateRead])
async def list_certificates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    user_id: Annotated[int | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list:
    if current.role == UserRole.student.value:
        rows = await certificate_repository.list_by_user(
            db, current.id, skip=skip, limit=limit
        )
        return list(rows)
    uid = user_id
    if uid is None:
        if not is_super_or_admin(current):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Indique user_id o sea admin",
            )
        rows = await certificate_repository.list(db, skip=skip, limit=limit)
        return list(rows)
    if uid != current.id and not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso")
    rows = await certificate_repository.list_by_user(db, uid, skip=skip, limit=limit)
    return list(rows)


@router.get("/view/{certificate_uuid}")
async def view_certificate_pdf_public(certificate_uuid: UUID) -> Response:
    """Sirve el PDF desde MinIO para visualización en el front (público, solo UUID)."""
    settings = get_settings()
    try:
        _require_minio(settings)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Almacenamiento de certificados no configurado.",
        )
    key = _minio_object_key(settings.minio_path_pdf, f"{certificate_uuid}.pdf")

    def load() -> bytes:
        return get_minio_client(settings).download_bytes(key)

    try:
        data = await asyncio.to_thread(load)
    except S3Error as e:
        code = str(getattr(e, "code", "") or "").lower()
        if code in ("nosuchkey", "notfound"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificado no encontrado",
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
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{certificate_uuid}.pdf"',
        },
    )


@router.get("/view/{certificate_uuid}/qr")
async def view_certificate_qr_public(certificate_uuid: UUID) -> Response:
    """Sirve el PNG del QR desde MinIO (público)."""
    settings = get_settings()
    try:
        _require_minio(settings)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Almacenamiento de certificados no configurado.",
        )
    key = _minio_object_key(settings.minio_path_qr, f"{certificate_uuid}.png")

    def load() -> bytes:
        return get_minio_client(settings).download_bytes(key)

    try:
        data = await asyncio.to_thread(load)
    except S3Error as e:
        code = str(getattr(e, "code", "") or "").lower()
        if code in ("nosuchkey", "notfound"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Código QR no encontrado",
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
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{certificate_uuid}.png"',
        },
    )


@router.get("/{certificate_id}", response_model=CertificateRead)
async def get_certificate(
    certificate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    cert = await certificate_repository.get_by_id(db, certificate_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certificado no encontrado"
        )
    if current.role == UserRole.student.value:
        if cert.user_id != current.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso"
            )
        return cert
    if not is_super_or_admin(current) and cert.user_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso")
    return cert


@router.post("", response_model=CertificateRead, status_code=status.HTTP_201_CREATED)
async def create_certificate(
    body: CertificateIssueRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    try:
        return await certificate_service.issue_certificate(
            db,
            admin=current,
            user_id=body.user_id,
            certificate_type_id=body.certificate_type_id,
            issued_at=body.issued_at,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.patch("/{certificate_id}", response_model=CertificateRead)
async def update_certificate(
    certificate_id: int,
    body: CertificateUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    if not is_super_or_admin(current):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores"
        )
    cert = await certificate_repository.get_by_id(db, certificate_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certificado no encontrado"
        )
    payload = body.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] is not None:
        payload["status"] = payload["status"].value
    try:
        return await certificate_service.apply_certificate_update(
            db, admin=current, cert=cert, fields=payload
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.delete("/{certificate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(
    certificate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> None:
    if not is_super_or_admin(current):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores"
        )
    cert = await certificate_repository.get_by_id(db, certificate_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Certificado no encontrado"
        )
    await certificate_service.delete_certificate(db, admin=current, cert=cert)

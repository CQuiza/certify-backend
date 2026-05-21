"""Lógica de emisión y campos automáticos de certificados."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings
from app.models.certificate import Certificate
from app.models.certificate_audit import CertificateAudit
from app.models.enums import CertificateAuditAction, CertificateStatus, UserRole
from app.models.user import User
from app.repositories.certificate_repository import certificate_repository
from app.repositories.certificate_type_repository import certificate_type_repository
from app.repositories.user_repository import user_repository
from app.services.datetime_utils import compute_certificate_expires_at
from app.utils.certificate_editor import (
    CertificateEditor,
    CertificateEditorData,
    apply_revoked_watermark_pdf,
)
from app.utils.make_qr_code import MakeQRCode
from app.utils.minio_client import get_minio_client

_APP_ROOT = Path(__file__).resolve().parent.parent


def _resolve_under_app(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else _APP_ROOT / p


def _student_display_name(user: User) -> str:
    parts = [user.name, user.first_last_name, user.second_last_name or ""]
    return " ".join(x for x in parts if x).strip()


def _minio_object_key(prefix: str, filename: str) -> str:
    pr = prefix.strip().strip("/")
    return f"{pr}/{filename}" if pr else filename


def _require_minio(settings: Settings) -> None:
    if not (settings.minio_access_key and settings.minio_secret_key):
        msg = "MinIO es obligatorio: defina MINIO_ACCESS_KEY y MINIO_SECRET_KEY."
        raise RuntimeError(msg)


def _issued_date(cert: Certificate) -> datetime:
    t = cert.issued_at
    if t is None:
        return datetime.now(UTC)
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)
    return t


class CertificateService:
    async def issue_certificate(
        self,
        db: AsyncSession,
        *,
        admin: User,
        user_id: int,
        certificate_type_id: int,
        issued_at: datetime | None = None,
    ):
        """Crea certificado; PDF/QR solo en MinIO; registra auditoría."""
        if admin.role not in (UserRole.superuser.value, UserRole.admin.value):
            raise PermissionError("Solo administradores pueden emitir certificados")

        ct = await certificate_type_repository.get_by_id(db, certificate_type_id)
        if not ct:
            raise ValueError("Tipo de certificado no existe")

        student = await user_repository.get_by_id(db, user_id)
        if not student or student.role != UserRole.student.value:
            raise ValueError("El usuario destino debe ser estudiante")

        if issued_at is not None:
            # Si la fecha viene de la API sin zona horaria (naive), le asignamos UTC
            if issued_at.tzinfo is None:
                issued_at = issued_at.replace(tzinfo=UTC)
        else:
            # Si no se envía, se usa la fecha y hora actual del servidor por defecto
            issued_at = datetime.now(UTC)

        expires_at = compute_certificate_expires_at(
            issued_at,
            ct.validity_type,
            ct.validity_value,
        )
        settings = get_settings()
        _require_minio(settings)

        base = settings.base_url.rstrip("/")
        api = settings.api_v1_prefix.rstrip("/")

        cert = await certificate_repository.create(
            db,
            certificate_type_id=certificate_type_id,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
            status=CertificateStatus.active.value,
            qr_code_url=None,
            pdf_url=None,
        )
        uid = str(cert.unique_id)
        cert.pdf_url = f"{base}{api}/certificates/view/{uid}"
        cert.qr_code_url = f"{base}{api}/certificates/view/{uid}/qr"
        await db.flush()
        await db.refresh(cert)

        verify_url = f"{base}/verify/{uid}"
        box = max(4, min(14, settings.qr_size // 20))
        qr_io = MakeQRCode(box_size=box).to_bytesio(verify_url)

        tpl = _resolve_under_app(settings.certificate_template_pdf)
        editor = CertificateEditor(tpl)
        overlay = CertificateEditorData(
            issued_on=issued_at.date(),
            student_full_name=_student_display_name(student),
            identity_type=student.identity_type,
            identity_number=student.identity_number,
            certificate_type_kind=ct.type,
            certificate_type_name=ct.name,
            hours=ct.hours,
        )
        pdf_io = editor.build_merged_pdf(overlay, qr_io)

        pdf_bytes = pdf_io.getvalue()
        qr_io.seek(0)
        qr_bytes = qr_io.read()

        def upload() -> None:
            mc = get_minio_client(settings)
            mc.ensure_bucket()
            pdf_key = _minio_object_key(settings.minio_path_pdf, f"{uid}.pdf")
            qr_key = _minio_object_key(settings.minio_path_qr, f"{uid}.png")
            mc.upload_bytes(
                pdf_key,
                pdf_bytes,
                content_type="application/pdf",
            )
            mc.upload_bytes(
                qr_key,
                qr_bytes,
                content_type="image/png",
            )

        try:
            await asyncio.to_thread(upload)
        except Exception as exc:
            msg = "No se pudo subir el PDF o el QR a MinIO (endpoint, credenciales o red)."
            raise RuntimeError(msg) from exc

        audit = CertificateAudit(
            certificate_id=cert.id,
            certificate_unique_id=cert.unique_id,
            action=CertificateAuditAction.issued.value,
            performed_by=admin.id,
        )
        db.add(audit)
        await db.flush()
        return cert

    async def _minio_apply_revoked_watermark(
        self, settings: Settings, uid: str
    ) -> None:
        def go() -> None:
            mc = get_minio_client(settings)
            key = _minio_object_key(settings.minio_path_pdf, f"{uid}.pdf")
            raw = mc.download_bytes(key)
            stamped = apply_revoked_watermark_pdf(
                raw,
                watermark_text=settings.certificate_revoked_watermark_text,
            )
            mc.upload_bytes(key, stamped, content_type="application/pdf")

        await asyncio.to_thread(go)

    async def _minio_restore_clean_pdf(
        self,
        db: AsyncSession,
        settings: Settings,
        cert: Certificate,
    ) -> None:
        student = await user_repository.get_by_id(db, cert.user_id)
        ct = await certificate_type_repository.get_by_id(db, cert.certificate_type_id)
        if not student or not ct:
            msg = (
                "No se puede regenerar el PDF: falta estudiante o tipo de certificado."
            )
            raise ValueError(msg)

        issued_at = _issued_date(cert)
        uid = str(cert.unique_id)
        base = settings.base_url.rstrip("/")
        verify_url = f"{base}/verify/{uid}"
        box = max(4, min(14, settings.qr_size // 20))
        qr_io = MakeQRCode(box_size=box).to_bytesio(verify_url)
        tpl = _resolve_under_app(settings.certificate_template_pdf)
        editor = CertificateEditor(tpl)
        overlay = CertificateEditorData(
            issued_on=issued_at.date(),
            student_full_name=_student_display_name(student),
            identity_type=student.identity_type,
            identity_number=student.identity_number,
            certificate_type_kind=ct.type,
            certificate_type_name=ct.name,
            hours=ct.hours,
        )
        pdf_io = editor.build_merged_pdf(overlay, qr_io)
        pdf_bytes = pdf_io.getvalue()

        def upload() -> None:
            mc = get_minio_client(settings)
            key = _minio_object_key(settings.minio_path_pdf, f"{uid}.pdf")
            mc.upload_bytes(key, pdf_bytes, content_type="application/pdf")

        await asyncio.to_thread(upload)

    async def apply_certificate_update(
        self,
        db: AsyncSession,
        *,
        admin: User,
        cert: Certificate,
        fields: dict[str, object],
    ) -> Certificate:
        """Actualiza campos permitidos; marca de agua en MinIO al revocar."""
        settings = get_settings()
        old_status = cert.status
        updated = await certificate_repository.update(db, cert, fields)
        if (
            updated.status == CertificateStatus.revoked.value
            and old_status != CertificateStatus.revoked.value
        ):
            db.add(
                CertificateAudit(
                    certificate_id=updated.id,
                    certificate_unique_id=updated.unique_id,
                    action=CertificateAuditAction.revoked.value,
                    performed_by=admin.id,
                ),
            )
            await db.flush()
            _require_minio(settings)
            try:
                await self._minio_apply_revoked_watermark(
                    settings,
                    str(updated.unique_id),
                )
            except Exception as exc:
                msg = "No se pudo actualizar el PDF en MinIO con la marca REVOCADO."
                raise RuntimeError(msg) from exc
        elif (
            updated.status == CertificateStatus.active.value
            and old_status == CertificateStatus.revoked.value
        ):
            db.add(
                CertificateAudit(
                    certificate_id=updated.id,
                    certificate_unique_id=updated.unique_id,
                    action=CertificateAuditAction.active.value,
                    performed_by=admin.id,
                ),
            )
            await db.flush()
            _require_minio(settings)
            try:
                await self._minio_restore_clean_pdf(db, settings, updated)
            except Exception as exc:
                msg = "No se pudo restaurar el PDF en MinIO sin marca de agua."
                raise RuntimeError(msg) from exc
        return updated

    async def delete_certificate(
        self,
        db: AsyncSession,
        *,
        admin: User,
        cert: Certificate,
    ) -> None:
        """Elimina el certificado tras registrar acción deleted en auditoría."""
        db.add(
            CertificateAudit(
                certificate_id=cert.id,
                certificate_unique_id=cert.unique_id,
                action=CertificateAuditAction.deleted.value,
                performed_by=admin.id,
            ),
        )
        await db.flush()
        await certificate_repository.delete(db, cert)


certificate_service = CertificateService()

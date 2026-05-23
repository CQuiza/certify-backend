"""
Ejecuta las tareas diarias de expiración de certificados y backups de base de datos.
"""

import asyncio
import os
import subprocess
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.settings import get_settings
from app.models.certificate import Certificate
from app.models.certificate_audit import CertificateAudit
from app.models.enums import CertificateStatus, CertificateAuditAction, WorkerStatus
from app.utils.certificate_editor import apply_revoked_watermark_pdf
from app.utils.minio_client import get_minio_client
from app.utils.worker_audit import log_worker_action

@shared_task(name="app.workers.tasks.check_expired_certificates")
def check_expired_certificates():
    """
    Revisa certificados expirados, aplica marca de agua y actualiza la BD.
    """
    asyncio.run(_async_check_expired_certificates())


async def _async_check_expired_certificates():
    settings = get_settings()
    now = datetime.now(timezone.utc)
    started_at = now
    task_name = "check_expired_certificates"
    processed = 0
    errors = []

    async with AsyncSessionLocal() as session:
        await log_worker_action(
            session, task_name=task_name, status=WorkerStatus.running.value,
            started_at=started_at,
        )

        stmt = select(Certificate).where(
            Certificate.status == CertificateStatus.active.value,
            Certificate.expires_at <= now
        )
        result = await session.execute(stmt)
        certificates = result.scalars().all()

        if not certificates:
            await log_worker_action(
                session, task_name=task_name, status=WorkerStatus.success.value,
                started_at=started_at, finished_at=datetime.now(timezone.utc),
                details="No se encontraron certificados expirados",
            )
            await session.commit()
            return

        minio_client = get_minio_client(settings)
        minio_client.ensure_bucket()

        system_bot_id = settings.system_bot_user_id

        for cert in certificates:
            uid_str = str(cert.unique_id)
            pdf_key = f"{settings.minio_path_pdf.strip('/')}/{uid_str}.pdf"

            try:
                raw_pdf = await asyncio.to_thread(minio_client.download_bytes, pdf_key)

                watermarked_pdf = apply_revoked_watermark_pdf(raw_pdf, watermark_text="EXPIRADO")

                await asyncio.to_thread(
                    minio_client.upload_bytes,
                    pdf_key,
                    watermarked_pdf,
                    content_type="application/pdf"
                )
            except Exception as e:
                errors.append(f"Certificado {cert.id}: {e}")
                continue

            cert.status = CertificateStatus.expired.value

            audit = CertificateAudit(
                certificate_id=cert.id,
                certificate_unique_id=cert.unique_id,
                action=CertificateAuditAction.expired.value,
                performed_by=system_bot_id,
            )
            session.add(audit)
            processed += 1

        await session.flush()

        details_parts = [f"{processed} certificados expirados"]
        if errors:
            details_parts.append(f"Errores: {'; '.join(errors)}")

        await log_worker_action(
            session, task_name=task_name, status=WorkerStatus.success.value,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
            details=" | ".join(details_parts),
        )

        await session.commit()


@shared_task(name="app.workers.tasks.backup_database_to_minio")
def backup_database_to_minio():
    """
    Realiza un backup de la base de datos usando pg_dump y lo sube a MinIO.
    """
    asyncio.run(_async_backup_database_to_minio())


async def _async_backup_database_to_minio():
    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    task_name = "backup_database_to_minio"

    host = settings.postgres_host
    port = settings.postgres_port
    user = settings.postgres_user
    password = settings.postgres_password
    db = settings.postgres_db

    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{db}_{timestamp}.sql"
    filepath = f"/tmp/{filename}"

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        "-h", str(host),
        "-p", str(port),
        "-U", str(user),
        "-d", str(db),
        "-F", "c",
        "-f", filepath,
    ]

    async with AsyncSessionLocal() as session:
        await log_worker_action(
            session, task_name=task_name, status=WorkerStatus.running.value,
            started_at=started_at,
        )
        await session.commit()

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True)

        minio_client = get_minio_client(settings)
        minio_client.ensure_bucket()

        object_name = f"{settings.minio_path_backup_db.strip('/')}/{filename}"

        minio_client.client.fput_object(
            minio_client.bucket,
            object_name,
            filepath,
        )

        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

        async with AsyncSessionLocal() as session:
            await log_worker_action(
                session, task_name=task_name, status=WorkerStatus.success.value,
                started_at=started_at, finished_at=datetime.now(timezone.utc),
                details=f"Backup {filename} subido a MinIO ({file_size} bytes)",
            )
            await session.commit()

    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode("utf-8", errors="replace")
        async with AsyncSessionLocal() as session:
            await log_worker_action(
                session, task_name=task_name, status=WorkerStatus.failed.value,
                started_at=started_at, finished_at=datetime.now(timezone.utc),
                details=f"pg_dump falló: {detail}",
            )
            await session.commit()
        raise e

    except Exception as e:
        async with AsyncSessionLocal() as session:
            await log_worker_action(
                session, task_name=task_name, status=WorkerStatus.failed.value,
                started_at=started_at, finished_at=datetime.now(timezone.utc),
                details=f"Error en backup: {e}",
            )
            await session.commit()
        raise

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

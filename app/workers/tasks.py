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
from app.models.enums import CertificateStatus, CertificateAuditAction
from app.utils.certificate_editor import apply_revoked_watermark_pdf
from app.utils.minio_client import get_minio_client

@shared_task(name="app.workers.tasks.check_expired_certificates")
def check_expired_certificates():
    """
    Revisa certificados expirados, aplica marca de agua y actualiza la BD.
    """
    asyncio.run(_async_check_expired_certificates())


async def _async_check_expired_certificates():
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        stmt = select(Certificate).where(
            Certificate.status == CertificateStatus.active.value,
            Certificate.expires_at <= now
        )
        result = await session.execute(stmt)
        certificates = result.scalars().all()

        if not certificates:
            return

        minio_client = get_minio_client(settings)
        minio_client.ensure_bucket()

        system_bot_id = settings.system_bot_user_id

        for cert in certificates:
            uid_str = str(cert.unique_id)
            pdf_key = f"{settings.minio_path_pdf.strip('/')}/{uid_str}.pdf"

            try:
                # 1. Download PDF
                raw_pdf = await asyncio.to_thread(minio_client.download_bytes, pdf_key)

                # 2. Apply watermark
                watermarked_pdf = apply_revoked_watermark_pdf(raw_pdf, watermark_text="EXPIRADO")

                # 3. Upload back
                await asyncio.to_thread(
                    minio_client.upload_bytes,
                    pdf_key,
                    watermarked_pdf,
                    content_type="application/pdf"
                )
            except Exception as e:
                # If there's an error with MinIO, log it and optionally continue or fail
                print(f"Error procesando PDF para el certificado {cert.id}: {e}")
                continue

            # 4. Update status
            cert.status = CertificateStatus.expired.value

            # 5. Audit entry
            audit = CertificateAudit(
                certificate_id=cert.id,
                certificate_unique_id=cert.unique_id,
                action=CertificateAuditAction.expired.value,
                performed_by=system_bot_id,
            )
            session.add(audit)

        # Commit changes
        await session.commit()


@shared_task(name="app.workers.tasks.backup_database_to_minio")
def backup_database_to_minio():
    """
    Realiza un backup de la base de datos usando pg_dump y lo sube a MinIO.
    """
    settings = get_settings()
    
    host = settings.postgres_host
    port = settings.postgres_port
    user = settings.postgres_user
    password = settings.postgres_password
    db = settings.postgres_db
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        "-F", "c",  # Custom format is generally preferred for pg_dump backups
        "-f", filepath
    ]
    
    try:
        # Run pg_dump
        subprocess.run(cmd, env=env, check=True, capture_output=True)
        
        # Upload to MinIO
        minio_client = get_minio_client(settings)
        minio_client.ensure_bucket()
        
        object_name = f"{settings.minio_path_backup_db.strip('/')}/{filename}"
        
        minio_client.client.fput_object(
            minio_client.bucket,
            object_name,
            filepath,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error executing pg_dump: {e.stderr.decode('utf-8')}")
        raise e
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

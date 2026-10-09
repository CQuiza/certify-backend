"""Envío de correos electrónicos usando fastapi-mail.

La configuración SMTP y las plantillas se resuelven desde la configuración
personalizable de plataforma (BD) con fallback al ``.env``. Se puede adjuntar
el logo de la organización como imagen inline (``cid:logo``).
"""

import logging
from datetime import datetime, timezone
from io import BytesIO

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from starlette.datastructures import Headers, UploadFile

from app.core.database import AsyncSessionLocal
from app.core.settings import get_settings
from app.core.tenant import tenant_ctx
from app.models.enums import EmailStatus
from app.services.email_template_service import RawHTML, email_template_service
from app.services.platform_settings_service import EmailConfig, platform_settings_service
from app.services.tenant_service import tenant_service

logger = logging.getLogger(__name__)

_LOGO_CID = "logo"
_LOGO_FILENAME = "certify_logo.png"


def build_connection_config(cfg: EmailConfig) -> ConnectionConfig | None:
    """Construye la config de fastapi-mail para una config efectiva."""
    if not cfg.host:
        return None
    from_email = cfg.from_email or (cfg.user or "")
    if not from_email:
        return None
    return ConnectionConfig(
        MAIL_USERNAME=cfg.user,
        MAIL_PASSWORD=cfg.password,
        MAIL_FROM=from_email,
        MAIL_FROM_NAME=cfg.from_name,
        MAIL_PORT=cfg.port,
        MAIL_SERVER=cfg.host,
        MAIL_STARTTLS=cfg.tls,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )


def inline_logo_attachments(logo_bytes: bytes | None) -> list[dict]:
    """Adjunta el logo como imagen inline referenciada por ``cid:logo``."""
    if not logo_bytes:
        return []
    upload = UploadFile(
        filename=_LOGO_FILENAME,
        file=BytesIO(logo_bytes),
        headers=Headers({"content-type": "image/png"}),
    )
    return [
        {
            "file": upload,
            "mime_type": "image",
            "mime_subtype": "png",
            "headers": {
                "Content-ID": f"<{_LOGO_CID}>",
                "Content-Disposition": f'inline; filename="{_LOGO_FILENAME}"',
            },
        }
    ]


def _base_context(ctx, template_context: dict, origin: str) -> dict:
    context: dict = dict(template_context)
    context["logo"] = ctx.logo_html
    context["app_name"] = ctx.app_name
    context["organization_name"] = ctx.organization_name or ctx.app_name
    context.setdefault("login_url", f"{origin}/login")
    return context


async def _dispatch(
    kind: str,
    recipients: list[str],
    template_context: dict,
    log_ref: str,
    *,
    tenant_id: int | None = None,
) -> None:
    """Resuelve config+plantilla y envía el correo del tipo dado."""
    try:
        if tenant_id is not None:
            async with tenant_ctx(tenant_id):
                await _dispatch_impl(kind, recipients, template_context, log_ref)
        else:
            await _dispatch_impl(kind, recipients, template_context, log_ref)
    except Exception:
        logger.exception("Error enviando correo '%s' a %s", kind, log_ref)


async def _dispatch_impl(kind, recipients, template_context, log_ref) -> None:
    async with AsyncSessionLocal() as session:
        origin = await tenant_service.current_public_origin(session)
        ctx = await platform_settings_service.get_email_context(session)
    if ctx is None:
        logger.warning(
            "SMTP no configurado. No se envió correo (%s) a %s", kind, log_ref
        )
        return
    template = ctx.templates.get(kind)
    if template is None:
        logger.warning("Plantilla '%s' no existe", kind)
        return
    context = _base_context(ctx, template_context, origin)
    subject, body = email_template_service.render(template, context)
    conf = build_connection_config(ctx.cfg)
    if conf is None:
        logger.warning("SMTP sin dirección de remitente — %s a %s", kind, log_ref)
        return
    message = MessageSchema(
        subject=subject,
        recipients=recipients,
        body=body,
        subtype="html",
        attachments=inline_logo_attachments(ctx.logo_bytes),
    )
    fm = FastMail(conf)
    await fm.send_message(message)
    logger.info("Correo '%s' enviado a %s", kind, log_ref)


async def send_credentials_email(email_to: str, password: str) -> None:
    """Envía un correo con las credenciales al usuario recién creado."""
    await _dispatch(
        "credentials",
        [email_to],
        {"email": email_to, "password": password},
        email_to,
    )


async def send_certificate_issued_email(
    email_to: str,
    student_name: str,
    certificate_uid: str,
    base_url: str,
    api_prefix: str = "",
    certificate_type_name: str | None = None,
) -> None:
    """Envía un correo notificando la emisión de un certificado."""
    verify_link = f"{base_url.rstrip('/')}{api_prefix}/certificates/view/{certificate_uid}"
    cert_line = ""
    if certificate_type_name:
        cert_line = RawHTML(
            f"<p><strong>Certificado:</strong> {certificate_type_name}</p>"
        )
    await _dispatch(
        "certificate_issued",
        [email_to],
        {
            "student_name": student_name,
            "verify_link": verify_link,
            "certificate_type": cert_line,
        },
        email_to,
    )


async def send_certificate_expired_email(
    email_to: str,
    student_name: str,
    certificate_uid: str,
    base_url: str | None = None,
    tenant_id: int | None = None,
) -> None:
    """Envía un correo notificando la expiración de un certificado."""
    await _dispatch(
        "certificate_expired",
        [email_to],
        {"student_name": student_name},
        email_to,
        tenant_id=tenant_id,
    )


async def send_test_email(email_to: str) -> None:
    """Envía un correo de prueba usando la configuración SMTP efectiva."""
    try:
        async with AsyncSessionLocal() as session:
            ctx = await platform_settings_service.get_email_context(session)
        if ctx is None:
            raise RuntimeError(
                "No hay configuración de correo: complete SMTP o defina variables en el .env"
            )
        conf = build_connection_config(ctx.cfg)
        if conf is None:
            raise RuntimeError("La configuración SMTP está incompleta")
        subject = f"Correo de prueba — {ctx.app_name}"
        body = (
            "<html><body style='font-family: Arial, sans-serif; padding: 20px;'>"
            + ctx.logo_html
            + "<h2>Correo de prueba</h2>"
            + "<p>Si estás viendo este correo, la configuración SMTP "
            + f"de <strong>{ctx.organization_name or ctx.app_name}</strong> funciona correctamente.</p>"
            + "</body></html>"
        )
        message = MessageSchema(
            subject=subject,
            recipients=[email_to],
            body=body,
            subtype="html",
            attachments=inline_logo_attachments(ctx.logo_bytes),
        )
        fm = FastMail(conf)
        await fm.send_message(message)
        logger.info("Correo de prueba enviado a %s", email_to)
    except Exception:
        logger.exception("Error enviando correo de prueba a %s", email_to)
        raise


# ── Wrappers con auditoría para BackgroundTasks ──────────────

from app.models.email_audit import EmailAudit


async def send_credentials_with_audit(
    email_to: str,
    password: str,
    user_name: str | None = None,
) -> None:
    """Envía credenciales y registra resultado en email_audit."""
    status = EmailStatus.failed.value
    error_text: str | None = None
    try:
        await send_credentials_email(email_to, password)
        status = EmailStatus.sent.value
    except Exception as e:
        error_text = str(e)
        logger.exception("Error en send_credentials_with_audit para %s", email_to)

    async with AsyncSessionLocal() as session:
        session.add(EmailAudit(
            user_name=user_name,
            email_to=email_to,
            email_type="credentials",
            status=status,
            error=error_text,
            sent_at=datetime.now(timezone.utc) if status == EmailStatus.sent.value else None,
        ))
        await session.commit()


async def send_issued_with_audit(
    email_to: str,
    student_name: str,
    certificate_uid: str,
    base_url: str,
    api_prefix: str,
    user_name: str | None = None,
    certificate_type_name: str | None = None,
) -> None:
    """Notifica emisión de certificado y registra resultado en email_audit."""
    status = EmailStatus.failed.value
    error_text: str | None = None
    try:
        await send_certificate_issued_email(
            email_to, student_name, certificate_uid, base_url, api_prefix, certificate_type_name
        )
        status = EmailStatus.sent.value
    except Exception as e:
        error_text = str(e)
        logger.exception("Error en send_issued_with_audit para %s", email_to)

    async with AsyncSessionLocal() as session:
        session.add(EmailAudit(
            user_name=user_name,
            email_to=email_to,
            email_type="certificate_issued",
            status=status,
            error=error_text,
            metadata_={"certificate_uid": certificate_uid},
            sent_at=datetime.now(timezone.utc) if status == EmailStatus.sent.value else None,
        ))
        await session.commit()


async def send_expired_with_audit(
    email_to: str,
    student_name: str,
    certificate_uid: str,
    user_name: str | None = None,
) -> None:
    """Notifica expiración de certificado y registra resultado en email_audit."""
    status = EmailStatus.failed.value
    error_text: str | None = None
    try:
        await send_certificate_expired_email(email_to, student_name, certificate_uid)
        status = EmailStatus.sent.value
    except Exception as e:
        error_text = str(e)
        logger.exception("Error en send_expired_with_audit para %s", email_to)

    async with AsyncSessionLocal() as session:
        session.add(EmailAudit(
            user_name=user_name,
            email_to=email_to,
            email_type="certificate_expired",
            status=status,
            error=error_text,
            metadata_={"certificate_uid": certificate_uid},
            sent_at=datetime.now(timezone.utc) if status == EmailStatus.sent.value else None,
        ))
        await session.commit()
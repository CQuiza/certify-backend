"""Envío de correos electrónicos usando fastapi-mail."""

import logging

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def _build_mail_config() -> ConnectionConfig | None:
    settings = get_settings()
    if not settings.smtp_host:
        return None
    return ConnectionConfig(
        MAIL_USERNAME=settings.smtp_user,
        MAIL_PASSWORD=settings.smtp_password,
        MAIL_FROM=settings.email_from,
        MAIL_PORT=settings.smtp_port,
        MAIL_SERVER=settings.smtp_host,
        MAIL_STARTTLS=settings.smtp_tls,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )


async def send_credentials_email(email_to: str, password: str) -> None:
    """Envía un correo con las credenciales al usuario recién creado."""
    conf = _build_mail_config()
    if conf is None:
        logger.warning("SMTP no configurado. No se envió correo de credenciales a %s", email_to)
        return

    message = MessageSchema(
        subject="Tus credenciales de acceso — Certify",
        recipients=[email_to],
        body=f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2>Bienvenido a Certify</h2>
    <p>Tu cuenta ha sido creada exitosamente. Estas son tus credenciales de acceso:</p>
    <p><strong>Correo:</strong> {email_to}</p>
    <p><strong>Contraseña:</strong> {password}</p>
    <p>Te recomendamos cambiar tu contraseña en tu primer inicio de sesión.</p>
</body>
</html>
""",
        subtype="html",
    )

    try:
        fm = FastMail(conf)
        await fm.send_message(message)
        logger.info("correo enviado exitoso")
    except Exception:
        logger.exception("Error al enviar correo a usuario")

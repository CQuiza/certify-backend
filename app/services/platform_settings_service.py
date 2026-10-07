"""Servicio de configuración personalizable de la plataforma.

Reúne organización/marca, configuración SMTP (cifrada) y plantillas de correo,
todo con mira a la fase multitenancy: cada consulta pasa por ``tenant_key``
(hoy siempre ``'default'`` via ``get_current_tenant``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret, password_is_set
from app.core.settings import get_settings
from app.models.platform_settings import (
    DEFAULT_DASHBOARD_MESSAGE,
    DEFAULT_TENANT_KEY,
    PlatformSettings,
)
from app.repositories.platform_settings_repository import platform_settings_repository
from app.services.email_template_service import (
    EmailTemplateService,
    build_logo_html,
)
from app.utils.email_templates import DEFAULT_TEMPLATES

logger = logging.getLogger(__name__)

_OBJECT_NAME = "certify_logo.png"

_DEFAULT_SMTP_PORT = 587


@dataclass(frozen=True)
class EmailConfig:
    """Configuración SMTP efectiva para enviar correos."""

    host: str
    port: int
    user: str = ""
    password: str = ""
    tls: bool = True
    from_email: str | None = None
    from_name: str | None = None


@dataclass
class EmailContext:
    """Todo lo necesario para renderizar y enviar un correo."""

    cfg: EmailConfig
    app_name: str
    organization_name: str | None
    templates: dict[str, object]
    logo_bytes: bytes | None = None
    logo_html: str = field(default="")


class PlatformSettingsService:
    async def get_or_create(self, db: AsyncSession) -> PlatformSettings:
        return await platform_settings_repository.get_or_create(
            db, DEFAULT_TENANT_KEY
        )

    # ── branding / organización ───────────────────────────────

    async def get_branding(self, db: AsyncSession) -> dict:
        row = await self.get_or_create(db)
        settings = get_settings()
        app_name = settings.project_name
        organization = row.organization_name or app_name
        template = row.dashboard_message or DEFAULT_DASHBOARD_MESSAGE
        from app.services.email_template_service import render

        message = render(template, {"app_name": app_name, "organization": organization})
        return {
            "organization_name": row.organization_name,
            "dashboard_message": message,
            "has_custom_logo": bool(
                row.branding_logo_object_key
                and settings.minio_access_key
                and settings.minio_secret_key
            ),
        }

    async def save_organization(
        self,
        db: AsyncSession,
        *,
        organization_name: str | None,
        dashboard_message: str | None,
        updated_by: int | None = None,
    ) -> dict:
        row = await self.get_or_create(db)
        await platform_settings_repository.update(
            db,
            row,
            {
                "organization_name": (organization_name or "").strip() or None,
                "dashboard_message": (dashboard_message or "").strip() or None,
                "updated_by": updated_by,
            },
        )
        logger.info("Configuración de organización actualizada — by=%s", updated_by)
        return await self.get_branding(db)

    # ── correo / SMTP ─────────────────────────────────────────

    async def get_email_settings(self, db: AsyncSession) -> dict:
        row = await self.get_or_create(db)
        return {
            "smtp_enabled": bool(row.smtp_enabled),
            "smtp_host": row.smtp_host,
            "smtp_port": row.smtp_port,
            "smtp_user": row.smtp_user,
            "smtp_password_set": password_is_set(row.smtp_password_encrypted),
            "smtp_tls": bool(row.smtp_tls),
            "email_from": row.email_from,
            "email_from_name": row.email_from_name,
        }

    async def save_email_settings(
        self,
        db: AsyncSession,
        *,
        smtp_enabled: bool,
        smtp_host: str | None,
        smtp_port: int | None,
        smtp_user: str | None,
        smtp_password: str | None,
        clear_smtp_password: bool,
        smtp_tls: bool,
        email_from: str | None,
        email_from_name: str | None,
        updated_by: int | None = None,
    ) -> dict:
        row = await self.get_or_create(db)

        fields: dict[str, object] = {
            "smtp_enabled": bool(smtp_enabled),
            "smtp_host": (smtp_host or "").strip() or None,
            "smtp_port": smtp_port,
            "smtp_user": (smtp_user or "").strip() or None,
            "smtp_tls": bool(smtp_tls),
            "email_from": (email_from or "").strip() or None,
            "email_from_name": (email_from_name or "").strip() or None,
            "updated_by": updated_by,
        }

        if clear_smtp_password:
            fields["smtp_password_encrypted"] = None
        elif smtp_password:
            fields["smtp_password_encrypted"] = encrypt_secret(smtp_password)

        await platform_settings_repository.update(db, row, fields)
        logger.info("Configuración SMTP actualizada — by=%s", updated_by)
        return await self.get_email_settings(db)

    async def resolve_email_config(self, db: AsyncSession) -> EmailConfig | None:
        row = await self.get_or_create(db)
        settings = get_settings()
        org_name = row.organization_name or settings.project_name

        if row.smtp_enabled and row.smtp_host:
            return EmailConfig(
                host=row.smtp_host,
                port=row.smtp_port or _DEFAULT_SMTP_PORT,
                user=row.smtp_user or "",
                password=decrypt_secret(row.smtp_password_encrypted) or "",
                tls=bool(row.smtp_tls),
                from_email=row.email_from or settings.email_from,
                from_name=row.email_from_name or org_name,
            )

        if settings.smtp_host:
            return EmailConfig(
                host=settings.smtp_host,
                port=settings.smtp_port or _DEFAULT_SMTP_PORT,
                user=settings.smtp_user or "",
                password=settings.smtp_password or "",
                tls=bool(settings.smtp_tls),
                from_email=settings.email_from,
                from_name=settings.project_name,
            )

        return None

    # ── plantillas ────────────────────────────────────────────

    async def list_email_templates(self, db: AsyncSession) -> list[dict]:
        row = await self.get_or_create(db)
        effective = await EmailTemplateService().list_effective(db, row.id)
        return [
            {
                "kind": t.kind,
                "subject": t.subject,
                "body_html": t.body_html,
                "is_custom": t.is_custom,
            }
            for t in effective
        ]

    async def get_email_template(self, db: AsyncSession, kind: str) -> dict:
        row = await self.get_or_create(db)
        t = await EmailTemplateService().get_effective_template(db, row.id, kind)
        return {
            "kind": t.kind,
            "subject": t.subject,
            "body_html": t.body_html,
            "is_custom": t.is_custom,
        }

    async def save_email_template(
        self,
        db: AsyncSession,
        *,
        kind: str,
        subject: str,
        body_html: str,
        is_enabled: bool,
        updated_by: int | None = None,
    ) -> dict:
        from app.repositories.email_template_repository import email_template_repository

        row = await self.get_or_create(db)
        await email_template_repository.upsert(
            db,
            platform_settings_id=row.id,
            kind=kind,
            subject=(subject or "").strip() or DEFAULT_TEMPLATES[kind]["subject"],
            body_html=body_html or DEFAULT_TEMPLATES[kind]["body_html"],
            is_enabled=is_enabled,
            updated_by=updated_by,
        )
        logger.info("Plantilla '%s' actualizada — by=%s", kind, updated_by)
        return await self.get_email_template(db, kind)

    async def restore_email_template(
        self, db: AsyncSession, kind: str, *, updated_by: int | None = None
    ) -> dict:
        from app.repositories.email_template_repository import email_template_repository

        row = await self.get_or_create(db)
        await email_template_repository.delete_by_kind(db, row.id, kind)
        logger.info("Plantilla '%s' restaurada a default — by=%s", kind, updated_by)
        return await self.get_email_template(db, kind)

    # ── contexto de envío (una sola sesión) ───────────────────

    async def get_email_context(self, db: AsyncSession) -> EmailContext | None:
        cfg = await self.resolve_email_config(db)
        if cfg is None:
            return None
        row = await self.get_or_create(db)
        settings = get_settings()
        effective = await EmailTemplateService().list_effective(db, row.id)
        templates = {t.kind: t for t in effective}
        logo_bytes = await self.get_logo_bytes(row)
        logo_html = build_logo_html(logo_bytes is not None, row.organization_name)
        return EmailContext(
            cfg=cfg,
            app_name=settings.project_name,
            organization_name=row.organization_name,
            templates=templates,
            logo_bytes=logo_bytes,
            logo_html=logo_html,
        )

    # ── logo (MinIO) ──────────────────────────────────────────

    def _logo_object_key(self, settings) -> str:
        prefix = settings.minio_path_branding.strip().strip("/")
        return f"{prefix}/{_OBJECT_NAME}" if prefix else _OBJECT_NAME

    async def get_logo_bytes(self, row: PlatformSettings | None = None) -> bytes | None:
        from app.utils.minio_client import get_minio_client

        settings = get_settings()
        if not (settings.minio_access_key and settings.minio_secret_key):
            return None
        if row is not None and not row.branding_logo_object_key:
            return None
        key = self._logo_object_key(settings)
        try:
            def _load() -> bytes:
                return get_minio_client(settings).download_bytes(key)

            return await asyncio.to_thread(_load)
        except Exception:
            logger.exception("No se pudo leer el logo de MinIO (%s)", key)
            return None

    async def save_logo(self, db: AsyncSession, data: bytes, *, updated_by: int | None = None) -> None:
        from app.utils.minio_client import get_minio_client

        settings = get_settings()
        if not (settings.minio_access_key and settings.minio_secret_key):
            raise ValueError("MinIO no configurado")

        key = self._logo_object_key(settings)

        def _go() -> None:
            client = get_minio_client(settings)
            client.ensure_bucket()
            client.upload_bytes(key, data, content_type="image/png")

        try:
            await asyncio.to_thread(_go)
        except Exception as exc:
            logger.exception("Error subiendo logo de marca")
            raise RuntimeError("No se pudo guardar el logo en MinIO") from exc

        row = await self.get_or_create(db)
        await platform_settings_repository.update(
            db, row, {"branding_logo_object_key": key, "updated_by": updated_by}
        )
        logger.info("Logo de marca actualizado — by=%s", updated_by)

    async def remove_logo(self, db: AsyncSession, *, updated_by: int | None = None) -> None:
        from app.utils.minio_client import get_minio_client

        settings = get_settings()
        row = await self.get_or_create(db)
        if settings.minio_access_key and settings.minio_secret_key:
            key = self._logo_object_key(settings)

            def _go() -> None:
                get_minio_client(settings).remove_object(key)

            try:
                await asyncio.to_thread(_go)
            except Exception:
                logger.exception("Error eliminando logo de marca")

        await platform_settings_repository.update(
            db,
            row,
            {"branding_logo_object_key": None, "updated_by": updated_by},
        )
        logger.info("Logo de marca restaurado a default — by=%s", updated_by)


platform_settings_service = PlatformSettingsService()
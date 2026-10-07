"""Servicio de plantillas de correo: resolución efectiva y render de placeholders."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.email_template_repository import email_template_repository
from app.utils.email_templates import DEFAULT_TEMPLATES, PLACEHOLDERS

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class RawHTML(str):
    """Marca un valor como HTML seguro (se inserta sin escapar)."""


@dataclass(frozen=True)
class EffectiveTemplate:
    kind: str
    subject: str
    body_html: str
    is_custom: bool


def get_placeholders() -> dict[str, str]:
    return dict(PLACEHOLDERS)


def render(text: str, context: dict[str, object]) -> str:
    """Sustituye ``{{key}}`` con el valor del contexto (escapa HTML).

    Los placeholders sin valor definido se conservan tal cual para que el
    autor de la plantilla detecte valores faltantes. Los valores marcados
    como :class:`RawHTML` se insertan sin escapar.
    """
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key)
        if value is None:
            return match.group(0)
        if isinstance(value, RawHTML):
            return str(value)
        return html.escape(str(value), quote=True)

    return _PLACEHOLDER_RE.sub(_sub, text)


def build_logo_html(exists: bool, organization_name: str | None = None) -> str:
    if not exists:
        return ""
    alt = html.escape(organization_name or "logo", quote=True)
    return (
        f'<img src="cid:logo" alt="{alt}" '
        f'style="max-height:80px; margin-bottom:16px;" />'
    )


class EmailTemplateService:
    """Retorna la plantilla efectiva (personalizada en BD o default)."""

    async def get_effective_template(
        self, db: AsyncSession, platform_settings_id: int, kind: str
    ) -> EffectiveTemplate:
        default = DEFAULT_TEMPLATES[kind]
        row = await email_template_repository.get_by_kind(
            db, platform_settings_id, kind
        )
        if row is not None and row.is_enabled:
            return EffectiveTemplate(
                kind=kind,
                subject=row.subject,
                body_html=row.body_html,
                is_custom=True,
            )
        return EffectiveTemplate(
            kind=kind,
            subject=default["subject"],
            body_html=default["body_html"],
            is_custom=False,
        )

    async def list_effective(
        self, db: AsyncSession, platform_settings_id: int
    ) -> list[EffectiveTemplate]:
        kinds = list(DEFAULT_TEMPLATES.keys())
        templates = {t.kind: t for t in await email_template_repository.list_by_settings(db, platform_settings_id)}
        result: list[EffectiveTemplate] = []
        for kind in kinds:
            row = templates.get(kind)
            default = DEFAULT_TEMPLATES[kind]
            if row is not None and row.is_enabled:
                result.append(
                    EffectiveTemplate(kind=kind, subject=row.subject, body_html=row.body_html, is_custom=True)
                )
            else:
                result.append(
                    EffectiveTemplate(kind=kind, subject=default["subject"], body_html=default["body_html"], is_custom=False)
                )
        return result

    def render(self, template: EffectiveTemplate, context: dict[str, object]) -> tuple[str, str]:
        return (
            render(template.subject, context),
            render(template.body_html, context),
        )


email_template_service = EmailTemplateService()
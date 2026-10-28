"""Inicialización de Sentry para API y workers."""

from __future__ import annotations

import logging
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_SENSITIVE_KEY = (
    "authorization",
    "cookie",
    "csrf",
    "email",
    "identity",
    "password",
    "secret",
    "token",
)


def _scrub(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Elimina datos personales y credenciales antes de enviar a Sentry."""
    del hint
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request["query_string"] = ""
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if any(part in key.lower() for part in _SENSITIVE_KEY):
                    headers.pop(key, None)

    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user.get("id")}

    extra = event.get("extra")
    if isinstance(extra, dict):
        for key in list(extra):
            if any(part in key.lower() for part in _SENSITIVE_KEY):
                extra[key] = "[redacted]"

    return event


def init_sentry(service: str = "api") -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        logger.warning("sentry-sdk no está instalado; Sentry deshabilitado")
        return

    integrations: list[Any] = [SqlalchemyIntegration()]
    if service == "api":
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        integrations.append(FastApiIntegration())
    if service == "worker":
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration())

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        integrations=integrations,
        before_send=_scrub,
        before_send_transaction=_scrub,
    )
    logger.info("Sentry inicializado — service=%s", service)

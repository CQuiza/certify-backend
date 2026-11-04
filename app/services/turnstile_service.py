"""Verificación de Cloudflare Turnstile para formularios públicos."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TIMEOUT_SECONDS = 5.0


async def verify_token(token: str | None, action: str = "register") -> bool:
    """Valida el token de Turnstile para la acción esperada.

    En desarrollo o tests sin secreto se omite la verificación. En producción
    el arranque exige ``TURNSTILE_SECRET_KEY`` y un token válido.
    """
    settings = get_settings()
    secret = settings.turnstile_secret_key.strip()
    if not secret:
        return settings.environment != "production"

    if not token or not token.strip():
        return False

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _VERIFY_URL,
                data={
                    "secret": secret,
                    "response": token.strip(),
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Turnstile: error al verificar el token")
        return False

    if not isinstance(payload, dict) or not payload.get("success"):
        codes = payload.get("error-codes") if isinstance(payload, dict) else None
        logger.warning("Turnstile: token rechazado — codes=%s", codes)
        return False

    if payload.get("action") != action:
        logger.warning(
            "Turnstile: acción inesperada — action=%s esperada=%s",
            payload.get("action"),
            action,
        )
        return False

    return True

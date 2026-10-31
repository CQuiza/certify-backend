"""Validación de URLs de contenido formativo."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}
_DRIVE_PATH = re.compile(r"^/(?:file|document)/d/[A-Za-z0-9_-]+")


def validate_optional_http_url(value: str | None) -> str | None:
    """Acepta solo URLs absolutas http/https sin credenciales."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > 2048:
        raise ValueError("La URL es demasiado larga")
    if any(char in text for char in ("\r", "\n", "\t")):
        raise ValueError("La URL contiene caracteres inválidos")

    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("La URL debe ser absoluta y usar http o https")
    if parsed.username or parsed.password:
        raise ValueError("La URL no debe incluir credenciales")
    return text


def validate_optional_drive_url(value: str | None) -> str | None:
    """Valida enlaces de Google Drive usados en tareas."""
    text = validate_optional_http_url(value)
    if text is None:
        return None

    parsed = urlsplit(text)
    if parsed.scheme != "https" or parsed.hostname not in _DRIVE_HOSTS:
        raise ValueError("El enlace debe pertenecer a Google Drive")
    if not _DRIVE_PATH.match(parsed.path):
        raise ValueError("El enlace de Google Drive no es válido")
    return text

"""Cabeceras HTTP seguras para descargas."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote


def content_disposition(filename: str, disposition: str = "inline") -> str:
    """Construye Content-Disposition con fallback ASCII y filename* UTF-8.

    Evita errores de codificación en proxies/Starlette cuando el nombre tiene
    espacios, acentos, comas o caracteres no ASCII.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', '_', ascii_name)
    ascii_name = re.sub(r'_+', '_', ascii_name).strip() or "archivo"
    encoded = quote(filename, safe="")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded}"
    )

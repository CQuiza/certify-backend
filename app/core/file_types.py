"""Detección de MIME por contenido para archivos subidos.

El MIME que declara el cliente (cabecera ``Content-Type`` multipart o campo
``mime_type`` del JSON) no es confiable: un archivo con bytes HTML puede
declararse como ``image/png`` y, si la API lo sirviera inline con ese tipo,
provocaría XSS almacenado en el origen de la API. Aquí se infiere el tipo real
a partir de los magic bytes y se exige coherencia con la extensión.
"""

from __future__ import annotations

import filetype

CANONICAL_MIME: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Solo estos tipos pueden servirse inline; el resto se fuerza a descarga.
INLINE_MIME = frozenset({"image/png", "image/jpeg", "application/pdf"})

_EXTENSION_ALIASES = {"jpeg": "jpg"}
_OOXML_EXTENSIONS = frozenset({"docx", "pptx", "xlsx"})
_ZIP_MAGIC = b"PK\x03\x04"


def normalize_extension(filename: str) -> str:
    """Devuelve la extensión normalizada (minúsculas y sin alias)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXTENSION_ALIASES.get(ext, ext)


def sniff_mime(data: bytes) -> str | None:
    """Infiera el MIME canónico desde los bytes, o ``None`` si no se reconoce."""
    kind = filetype.guess(data)
    if kind is None:
        return None
    extension = _EXTENSION_ALIASES.get(kind.extension, kind.extension)
    return CANONICAL_MIME.get(extension)


def is_inline_mime(mime_type: str | None) -> bool:
    """Solo imágenes PNG/JPEG y PDF pueden servirse con ``inline``."""
    return mime_type in INLINE_MIME


def validate_upload_content(data: bytes, filename: str) -> str:
    """Valida el contenido contra la extensión y devuelve el MIME canónico.

    Lanza ``ValueError`` con un mensaje apto para el usuario si el contenido no
    coincide con la extensión declarada o si el tipo no está permitido.
    """
    ext = normalize_extension(filename)
    if ext not in CANONICAL_MIME:
        raise ValueError(
            f"Extensión .{ext or '(sin extensión)'} no permitida. "
            f"Extensiones aceptadas: {', '.join(sorted(CANONICAL_MIME))}"
        )

    inferred = sniff_mime(data)
    if inferred is None and ext in _OOXML_EXTENSIONS and data.startswith(_ZIP_MAGIC):
        # Algunos OOXML se detectan como zip genérico; el magic PK es suficiente
        # para descartar HTML/scripts y aceptar el contenedor declarado.
        inferred = CANONICAL_MIME[ext]

    if inferred is None or inferred != CANONICAL_MIME[ext]:
        raise ValueError("El contenido del archivo no coincide con su extensión.")
    return inferred

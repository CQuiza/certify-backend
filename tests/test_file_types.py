"""Detección de MIME por contenido para subidas de archivos."""

import pytest

from app.core.file_types import (
    is_inline_mime,
    normalize_extension,
    sniff_mime,
    validate_upload_content,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32
_PDF = b"%PDF-1.4\n" + b"\x00" * 32
_HTML = b"<html><script>alert(1)</script></html>"


def test_png_is_validated_against_extension():
    assert validate_upload_content(_PNG, "foto.png") == "image/png"


def test_jpeg_extension_accepts_jpeg_content():
    assert validate_upload_content(_JPEG, "foto.jpeg") == "image/jpeg"
    assert validate_upload_content(_JPEG, "foto.jpg") == "image/jpeg"


def test_pdf_is_validated():
    assert validate_upload_content(_PDF, "guia.pdf") == "application/pdf"


def test_html_disguised_as_png_is_rejected():
    with pytest.raises(ValueError):
        validate_upload_content(_HTML, "foto.png")


def test_png_disguised_as_pdf_is_rejected():
    with pytest.raises(ValueError):
        validate_upload_content(_PNG, "guia.pdf")


def test_unknown_extension_is_rejected():
    with pytest.raises(ValueError):
        validate_upload_content(_HTML, "archivo.exe")


def test_ooxml_zip_container_is_accepted():
    data = b"PK\x03\x04" + b"\x00" * 64
    assert (
        validate_upload_content(data, "documento.docx")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_zip_disguised_as_png_is_rejected():
    with pytest.raises(ValueError):
        validate_upload_content(b"PK\x03\x04" + b"\x00" * 64, "foto.png")


def test_inline_only_for_safe_mimes():
    assert is_inline_mime("image/png")
    assert is_inline_mime("image/jpeg")
    assert is_inline_mime("application/pdf")
    assert not is_inline_mime("text/html")
    assert not is_inline_mime("image/svg+xml")
    assert not is_inline_mime(None)


def test_sniff_ignores_client_declared_type():
    assert sniff_mime(_HTML) is None
    assert normalize_extension("FOTO.JPEG") == "jpg"

"""Cabeceras de descarga con nombres problemáticos."""

from app.core.http_headers import content_disposition


def test_content_disposition_encodes_spaces_and_accents():
    header = content_disposition("Tarea módulo 1.pdf", "attachment")

    assert header.startswith("attachment;")
    assert 'filename="Tarea modulo 1.pdf"' in header
    assert "filename*=UTF-8''Tarea%20m%C3%B3dulo%201.pdf" in header


def test_content_disposition_sanitizes_unsafe_ascii():
    header = content_disposition('archivo "raro";.pdf', "inline")

    assert 'filename="archivo _raro_.pdf"' in header
    assert "filename*=UTF-8''" in header

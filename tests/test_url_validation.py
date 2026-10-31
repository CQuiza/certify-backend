"""Validación de URLs de contenido y enlaces de Drive."""

import pytest
from pydantic import ValidationError

from app.core.url_validation import (
    validate_optional_drive_url,
    validate_optional_http_url,
)
from app.schemas.lesson import LessonCreate
from app.schemas.lesson_task import LessonTaskCreate


def test_http_url_accepts_https_and_http():
    assert validate_optional_http_url("https://example.com/video.mp4") == "https://example.com/video.mp4"
    assert validate_optional_http_url("http://example.com/file.pdf") == "http://example.com/file.pdf"
    assert validate_optional_http_url(None) is None
    assert validate_optional_http_url("   ") is None


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "//evil.example.com/file",
        "/relative/path",
        "https://user:pass@example.com/file",
    ],
)
def test_http_url_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        validate_optional_http_url(value)


def test_drive_url_requires_exact_host_and_file_path():
    valid = "https://drive.google.com/file/d/abc_123-XYZ/view"
    assert validate_optional_drive_url(valid) == valid

    for value in [
        "https://drive.google.com.evil.com/file/d/abc/view",
        "http://drive.google.com/file/d/abc/view",
        "https://example.com/file/d/abc/view",
        "https://drive.google.com/folder/abc",
    ]:
        with pytest.raises(ValueError):
            validate_optional_drive_url(value)


def test_lesson_schema_rejects_javascript_url():
    with pytest.raises(ValidationError):
        LessonCreate(
            module_id=1,
            title="Lección",
            video_content_url="javascript:alert(1)",
            order_index=0,
        )


def test_task_schema_rejects_non_drive_link():
    with pytest.raises(ValidationError):
        LessonTaskCreate(
            lesson_id=1,
            title="Tarea",
            file_type="google_drive",
            google_drive_link="https://example.com/file/d/abc",
        )

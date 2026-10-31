"""Extensiones permitidas para archivos de lección."""

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.lesson_files import _validate_file_extension


def test_jpeg_extension_is_allowed():
    _validate_file_extension("foto de clase.jpeg")


def test_unknown_extension_is_rejected():
    with pytest.raises(HTTPException):
        _validate_file_extension("archivo.exe")

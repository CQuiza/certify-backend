"""Esquemas de logs de la plataforma (monitorización)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_LEVELS = ("debug", "info", "warning", "error", "critical")
_ALLOWED_SOURCES = ("api", "worker", "frontend")


class SystemLogCreate(BaseModel):
    """Payload para registrar un log (p. ej. errores del frontend)."""

    level: str = Field(default="error")
    source: str = Field(default="frontend")
    event: str = Field(..., max_length=255)
    detail: str | None = None
    stacktrace: str | None = None
    path: str | None = Field(default=None, max_length=255)

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        v = (v or "error").lower()
        return v if v in _ALLOWED_LEVELS else "error"

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        v = (v or "frontend").lower()
        return v if v in _ALLOWED_SOURCES else "frontend"


class SystemLogRead(BaseModel):
    id: int
    level: str
    source: str
    event: str
    detail: str | None
    stacktrace: str | None
    request_id: str | None
    path: str | None
    method: str | None
    status_code: int | None
    user_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemLogListResponse(BaseModel):
    items: list[SystemLogRead]
    total: int
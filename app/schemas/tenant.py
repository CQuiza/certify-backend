"""Esquemas de tenants."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_SLUG_RE = r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$"


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., max_length=100)
    admin_email: EmailStr
    admin_name: str | None = Field(default=None, max_length=255)
    admin_password: str | None = Field(default=None, max_length=255)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        import re

        v = v.strip().lower()
        if not re.fullmatch(_SLUG_RE, v):
            raise ValueError(
                "Slug inválido: solo minúsculas, números y guiones (no al inicio/fin)"
            )
        return v


class TenantStatusUpdate(BaseModel):
    is_active: bool


class TenantRead(BaseModel):
    id: int
    name: str
    slug: str
    domain: str | None
    is_active: bool
    created_at: str | None = None
    total_users: int = 0
    total_courses: int = 0
    total_certificates: int = 0

    model_config = ConfigDict(from_attributes=True)


class TenantCreated(TenantRead):
    """Resultado de creación: incluye la contraseña del admin UNA sola vez."""

    admin_password: str | None = None


class AdminPasswordReset(BaseModel):
    admin_email: EmailStr


class TenantResetResult(BaseModel):
    detail: str
    password: str | None = None
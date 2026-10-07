"""Esquemas de configuración personalizable de la plataforma."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import EmailTemplateKind

_EMAIL_TEMPLATE_KINDS = {k.value for k in EmailTemplateKind}


class BrandingRead(BaseModel):
    """Marca visible: qué se muestra en dashboard/sidebar (autenticado)."""

    organization_name: str | None
    dashboard_message: str
    has_custom_logo: bool


class OrganizationUpdate(BaseModel):
    """Update de organización/marca (superuser)."""

    organization_name: str | None = Field(default=None, max_length=255)
    dashboard_message: str | None = Field(default=None, max_length=5000)


class EmailSettingsRead(BaseModel):
    """Config SMTP expuesta; la contraseña jamás se devuelve."""

    smtp_enabled: bool
    smtp_host: str | None
    smtp_port: int | None
    smtp_user: str | None
    smtp_password_set: bool
    smtp_tls: bool
    email_from: EmailStr | None
    email_from_name: str | None


class EmailSettingsUpdate(BaseModel):
    """Update de SMTP. ``smtp_password`` no vacío = setear; ``clear_smtp_password`` = borrar."""

    smtp_enabled: bool = False
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_user: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=255)
    clear_smtp_password: bool = False
    smtp_tls: bool = True
    email_from: EmailStr | None = None
    email_from_name: str | None = Field(default=None, max_length=255)

    @field_validator("smtp_password")
    @classmethod
    def _strip_password(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            return v or None
        return v


class EmailTemplateRead(BaseModel):
    kind: str
    subject: str
    body_html: str
    is_custom: bool

    model_config = ConfigDict(from_attributes=True)


class EmailTemplateUpdate(BaseModel):
    subject: str = Field(..., max_length=255)
    body_html: str = Field(..., max_length=20000)
    is_enabled: bool = True


class EmailTemplatesListRead(BaseModel):
    items: list[EmailTemplateRead]
    placeholders: dict[str, str]


class TestEmailRequest(BaseModel):
    email_to: EmailStr
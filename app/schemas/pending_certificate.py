"""Esquemas de solicitudes de certificado en proceso."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PendingCertificateCreate(BaseModel):
    user_id: int
    course_id: int
    issued_at: datetime | None = Field(
        default=None, description="Fecha de emisión a aplicar cuando se complete el curso"
    )
    validity_extension: int | None = Field(
        default=None, description="Sobreescribe la vigencia del tipo (en años)"
    )
    hours: int | None = Field(
        default=None, ge=0, description="Sobreescribe la intensidad horaria"
    )


class PendingCertificateRead(BaseModel):
    id: int
    user_id: int
    course_id: int
    certificate_type_id: int | None
    status: str
    created_by: int | None
    issued_at_override: datetime | None
    validity_extension: int | None
    hours: int | None
    issued_certificate_id: int | None
    created_at: datetime
    issued_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
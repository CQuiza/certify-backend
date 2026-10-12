"""Curso."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CourseStatus


class CourseCreate(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    certificate_type_id: int | None = None
    teacher_id: int | None = None
    status: CourseStatus = CourseStatus.draft
    price: Decimal = Decimal("0")
    is_for_sale: bool = False


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    certificate_type_id: int | None = None
    teacher_id: int | None = None
    status: CourseStatus | None = None
    price: Decimal | None = None
    is_for_sale: bool | None = None

    model_config = ConfigDict(extra="forbid")


class CourseRead(BaseModel):
    id: int
    title: str
    description: str | None
    certificate_type_id: int | None
    teacher_id: int | None
    created_at: datetime
    updated_at: datetime
    status: CourseStatus
    price: Decimal | None = None
    is_for_sale: bool = False

    model_config = ConfigDict(from_attributes=True)


class CoursePublicRead(BaseModel):
    """Listado público (catálogo)."""

    id: int
    title: str
    description: str | None
    status: CourseStatus
    price: Decimal | None = None
    is_for_sale: bool = False

    model_config = ConfigDict(from_attributes=True)

"""Archivos de lección."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LessonFileCreate(BaseModel):
    original_filename: str
    mime_type: str | None = None
    order_index: int = 0


class LessonFileUpdate(BaseModel):
    original_filename: str | None = None
    mime_type: str | None = None
    order_index: int | None = None
    model_config = ConfigDict(extra="forbid")


class LessonFileRead(BaseModel):
    id: int
    lesson_id: int
    original_filename: str | None
    mime_type: str | None
    file_url: str | None
    order_index: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

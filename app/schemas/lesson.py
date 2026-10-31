"""Lección."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.url_validation import validate_optional_http_url


class LessonCreate(BaseModel):
    module_id: int
    title: str = Field(..., max_length=255)
    text_content: str | None = None
    image_content_url: str | None = None
    video_content_url: str | None = None
    file_content_url: str | None = None
    order_index: int

    @field_validator("image_content_url", "video_content_url", "file_content_url")
    @classmethod
    def _validate_urls(cls, value: str | None) -> str | None:
        return validate_optional_http_url(value)


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    text_content: str | None = None
    image_content_url: str | None = None
    video_content_url: str | None = None
    file_content_url: str | None = None
    order_index: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("image_content_url", "video_content_url", "file_content_url")
    @classmethod
    def _validate_urls(cls, value: str | None) -> str | None:
        return validate_optional_http_url(value)


class LessonRead(BaseModel):
    id: int
    module_id: int
    title: str
    text_content: str | None
    image_content_url: str | None
    video_content_url: str | None
    file_content_url: str | None
    order_index: int

    model_config = ConfigDict(from_attributes=True)

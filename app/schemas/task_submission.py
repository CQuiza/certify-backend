"""Entrega de tarea."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TaskSubmissionRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    file_url: str
    original_filename: str
    mime_type: str
    submitted_at: datetime
    score: Decimal | None = None
    feedback: str | None = None
    passed: bool = False
    graded_by: int | None = None
    graded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskSubmissionWithUserRead(TaskSubmissionRead):
    user_name: str | None = None
    user_email: str | None = None
    grader_name: str | None = None


class GradeRequest(BaseModel):
    score: float = Field(..., ge=0, le=100)
    feedback: str | None = Field(default=None, max_length=2000)
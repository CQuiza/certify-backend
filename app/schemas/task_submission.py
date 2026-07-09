"""Entrega de tarea."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskSubmissionRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    file_url: str
    original_filename: str
    mime_type: str
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskSubmissionWithUserRead(TaskSubmissionRead):
    user_name: str | None = None
    user_email: str | None = None

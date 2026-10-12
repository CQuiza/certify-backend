"""Entrega de tarea por estudiante."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import TenantScoped

if TYPE_CHECKING:
    from app.models.lesson_task import LessonTask
    from app.models.user import User


class TaskSubmission(TenantScoped, Base):
    __tablename__ = "task_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lesson_tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(127), default="application/pdf", server_default="application/pdf"
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # ── Calificación y trazabilidad ───────────────────────────
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    graded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[LessonTask] = relationship("LessonTask", backref="submissions")
    user: Mapped[User] = relationship("User", backref="task_submissions", foreign_keys=[user_id])
    grader: Mapped[User | None] = relationship("User", foreign_keys=[graded_by])

    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="_task_user_uc"),
    )

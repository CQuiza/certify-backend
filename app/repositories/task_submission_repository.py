"""Repositorio de entregas de tareas."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.task_submission import TaskSubmission


class TaskSubmissionRepository:
    async def get_by_id(
        self, db: AsyncSession, submission_id: int
    ) -> TaskSubmission | None:
        r = await db.execute(
            select(TaskSubmission)
            .where(TaskSubmission.id == submission_id)
            .options(joinedload(TaskSubmission.user))
        )
        return r.unique().scalar_one_or_none()

    async def get_by_task_and_user(
        self, db: AsyncSession, task_id: int, user_id: int
    ) -> TaskSubmission | None:
        r = await db.execute(
            select(TaskSubmission).where(
                TaskSubmission.task_id == task_id,
                TaskSubmission.user_id == user_id,
            )
        )
        return r.scalar_one_or_none()

    async def list_by_task(
        self, db: AsyncSession, task_id: int
    ) -> Sequence[TaskSubmission]:
        r = await db.execute(
            select(TaskSubmission)
            .where(TaskSubmission.task_id == task_id)
            .options(joinedload(TaskSubmission.user))
            .order_by(TaskSubmission.submitted_at.desc())
        )
        return r.unique().scalars().all()

    async def list_by_tasks_and_user(
        self, db: AsyncSession, task_ids: list[int], user_id: int
    ) -> Sequence[TaskSubmission]:
        if not task_ids:
            return []
        r = await db.execute(
            select(TaskSubmission)
            .where(
                TaskSubmission.task_id.in_(task_ids),
                TaskSubmission.user_id == user_id,
            )
            .order_by(TaskSubmission.submitted_at.desc())
        )
        return r.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        user_id: int,
        file_url: str,
        original_filename: str,
        mime_type: str = "application/pdf",
    ) -> TaskSubmission:
        sub = TaskSubmission(
            task_id=task_id,
            user_id=user_id,
            file_url=file_url,
            original_filename=original_filename,
            mime_type=mime_type,
        )
        db.add(sub)
        await db.flush()
        await db.refresh(sub)
        return sub

    async def delete(self, db: AsyncSession, submission: TaskSubmission) -> None:
        await db.delete(submission)


task_submission_repository = TaskSubmissionRepository()

"""Endpoints de evaluaciones por módulo y progreso."""

import random
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.module import Module
from app.models.module_assessment import ModuleAssessment
from app.models.user import User
from app.models.user_assessment_attempt import UserAssessmentAttempt
from app.repositories.module_assessment_repository import (
    module_assessment_repository,
)
from app.repositories.module_repository import module_repository
from app.repositories.user_assessment_repository import (
    user_assessment_repository,
)
from app.schemas.module_assessment import (
    AllProgressSummary,
    AttemptRead,
    AttemptResult,
    CourseProgressSummary,
    ModuleAssessmentCreate,
    ModuleAssessmentRead,
    ModuleAssessmentReadTeacher,
    AssessmentSubmit,
)
from app.services.access import (
    is_super_or_admin,
    is_teacher,
    require_course_visible,
    teacher_owns_module,
)

router = APIRouter(tags=["module-assessments"])


async def _get_assessment_or_404(
    db: AsyncSession, assessment_id: int
) -> ModuleAssessment:
    assessment = await module_assessment_repository.get_by_id(db, assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluación no encontrada"
        )
    return assessment


async def _get_module_or_404(db: AsyncSession, module_id: int) -> Module:
    mod = await module_repository.get_by_id(db, module_id)
    if not mod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Módulo no encontrado"
        )
    return mod


# ─── GET /modules/{module_id}/assessment ───────────────────────


@router.get(
    "/modules/{module_id}/assessment",
)
async def get_module_assessment(
    module_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> ModuleAssessmentReadTeacher | ModuleAssessmentRead:
    mod = await _get_module_or_404(db, module_id)
    await require_course_visible(db, current, mod.course_id, need_content=True)

    assessment = await module_assessment_repository.get_by_module(db, module_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Este módulo no tiene evaluación"
        )

    if is_super_or_admin(current) or is_teacher(current):
        await teacher_owns_module(db, current, mod) if is_teacher(current) else None
        return ModuleAssessmentReadTeacher.model_validate(assessment)

    data = ModuleAssessmentRead.model_validate(assessment)
    for q in data.questions:
        q.options = random.sample(q.options, len(q.options))
    return data


# ─── POST /modules/{module_id}/assessment (upsert) ────────────


@router.post(
    "/modules/{module_id}/assessment",
    response_model=ModuleAssessmentReadTeacher,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_module_assessment(
    module_id: int,
    body: ModuleAssessmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    if current.role not in (
        UserRole.superuser.value,
        UserRole.admin.value,
        UserRole.teacher.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso"
        )
    mod = await _get_module_or_404(db, module_id)
    if is_teacher(current) and not await teacher_owns_module(db, current, mod):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No es su curso"
        )

    existing = await module_assessment_repository.get_by_module(db, module_id)

    questions_data = [q.model_dump() for q in body.questions]

    if existing:
        assessment = await module_assessment_repository.update_with_questions(
            db,
            existing,
            passing_score=body.passing_score,
            questions_data=questions_data,
        )
    else:
        assessment = await module_assessment_repository.create_with_questions(
            db,
            module_id=module_id,
            passing_score=body.passing_score,
            questions_data=questions_data,
        )

    return await module_assessment_repository.get_by_id(db, assessment.id)


# ─── DELETE /assessments/{assessment_id} ────────────────────


@router.delete(
    "/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_assessment(
    assessment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> None:
    if current.role not in (
        UserRole.superuser.value,
        UserRole.admin.value,
        UserRole.teacher.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso"
        )
    assessment = await _get_assessment_or_404(db, assessment_id)
    mod = await module_repository.get_by_id(db, assessment.module_id)
    if mod and is_teacher(current) and not await teacher_owns_module(db, current, mod):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No es su curso"
        )
    await module_assessment_repository.delete(db, assessment)


# ─── POST /assessments/{assessment_id}/submit ────────────────


@router.post(
    "/assessments/{assessment_id}/submit", response_model=AttemptResult
)
async def submit_assessment(
    assessment_id: int,
    body: AssessmentSubmit,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> AttemptResult:
    assessment = await _get_assessment_or_404(db, assessment_id)
    mod = await module_repository.get_by_id(db, assessment.module_id)
    if not mod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Módulo no encontrado"
        )
    await require_course_visible(db, current, mod.course_id, need_content=True)

    attempt = await user_assessment_repository.create_attempt(
        db, assessment_id=assessment_id, user_id=current.id
    )
    result = await user_assessment_repository.submit_answers(
        db,
        attempt,
        answers=[a.model_dump() for a in body.answers],
    )
    return result


# ─── GET /assessments/{assessment_id}/attempts ──────────────


@router.get(
    "/assessments/{assessment_id}/attempts", response_model=list[AttemptRead]
)
async def list_attempts(
    assessment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
) -> object:
    assessment = await _get_assessment_or_404(db, assessment_id)
    mod = await module_repository.get_by_id(db, assessment.module_id)
    if mod:
        await require_course_visible(db, current, mod.course_id, need_content=True)

    if is_super_or_admin(current):
        user_id: int | None = None
    elif is_teacher(current) and mod:
        if not await teacher_owns_module(db, current, mod):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso"
            )
        user_id = None
    else:
        user_id = current.id

    if user_id is not None:
        rows = await user_assessment_repository.get_attempts_by_assessment(
            db, assessment_id, user_id
        )
    else:
        r = await db.execute(
            sa_select(UserAssessmentAttempt)
            .where(UserAssessmentAttempt.assessment_id == assessment_id)
            .order_by(UserAssessmentAttempt.started_at.desc())
        )
        rows = r.scalars().all()

    return list(rows)


# ─── GET /user-progress/summary ─────────────────────────────
# ─── GET /user-progress/summary/{course_id} ─────────────────


@router.get("/user-progress/summary", response_model=AllProgressSummary)
async def get_all_progress(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    user_id: Annotated[int | None, Query()] = None,
) -> AllProgressSummary:
    uid = _resolve_progress_user(current, user_id)
    summaries, overall_pct = await user_assessment_repository.get_all_progress(
        db, uid
    )
    return AllProgressSummary(courses=summaries, overall_percent=overall_pct)


@router.get(
    "/user-progress/summary/{course_id}",
    response_model=CourseProgressSummary,
)
async def get_course_progress(
    course_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    user_id: Annotated[int | None, Query()] = None,
) -> CourseProgressSummary:
    uid = _resolve_progress_user(current, user_id)
    try:
        return await user_assessment_repository.get_course_progress(
            db, uid, course_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )


def _resolve_progress_user(current: User, user_id: int | None) -> int:
    if user_id is None:
        return current.id
    if user_id == current.id:
        return current.id
    if is_super_or_admin(current):
        return user_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tiene permiso para ver progreso de otros usuarios",
    )

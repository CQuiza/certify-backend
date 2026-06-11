"""Repositorio de intentos y progreso de evaluaciones."""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assessment_option import AssessmentOption
from app.models.assessment_question import AssessmentQuestion
from app.models.course import Course
from app.models.module import Module
from app.models.module_assessment import ModuleAssessment
from app.models.user_assessment_attempt import (
    UserAssessmentAnswer,
    UserAssessmentAttempt,
)
from app.schemas.module_assessment import (
    AnswerResult,
    AttemptResult,
    CourseProgressSummary,
    ModuleProgressItem,
)


class UserAssessmentRepository:
    async def create_attempt(
        self, db: AsyncSession, *, assessment_id: int, user_id: int
    ) -> UserAssessmentAttempt:
        attempt = UserAssessmentAttempt(
            assessment_id=assessment_id,
            user_id=user_id,
            started_at=datetime.now(timezone.utc),
        )
        db.add(attempt)
        await db.flush()
        await db.refresh(attempt)
        return attempt

    async def submit_answers(
        self,
        db: AsyncSession,
        attempt: UserAssessmentAttempt,
        answers: list[dict],
    ) -> AttemptResult:
        assessment = await db.execute(
            select(ModuleAssessment)
            .where(ModuleAssessment.id == attempt.assessment_id)
            .options(
                selectinload(ModuleAssessment.questions)
                .selectinload(AssessmentQuestion.options)
            )
        )
        assessment = assessment.scalar_one_or_none()
        if not assessment:
            raise ValueError("Assessment no encontrado")

        questions_map: dict[int, AssessmentQuestion] = {}
        options_map: dict[int, AssessmentOption] = {}
        for q in assessment.questions:
            questions_map[q.id] = q
            for opt in q.options:
                options_map[opt.id] = opt

        total_points = sum(q.points for q in assessment.questions)
        earned_points = 0
        answer_results: list[AnswerResult] = []

        for ans in answers:
            qid = ans["question_id"]
            oid = ans["selected_option_id"]

            question = questions_map.get(qid)
            if not question:
                raise ValueError(f"Pregunta {qid} no encontrada en el assessment")

            selected = options_map.get(oid)
            if not selected:
                raise ValueError(f"Opción {oid} no encontrada")
            if selected.question_id != qid:
                raise ValueError(
                    f"La opción {oid} no pertenece a la pregunta {qid}"
                )

            correct = selected.is_correct
            if correct:
                earned_points += question.points

            db_answer = UserAssessmentAnswer(
                attempt_id=attempt.id,
                question_id=qid,
                selected_option_id=oid,
                is_correct=correct,
            )
            db.add(db_answer)

            correct_option_id: int | None = None
            for opt in question.options:
                if opt.is_correct:
                    correct_option_id = opt.id
                    break

            answer_results.append(
                AnswerResult(
                    question_id=qid,
                    question_text=question.question_text,
                    selected_option_id=oid,
                    is_correct=correct,
                    correct_option_id=None,
                )
            )

        score = float(
            round((earned_points / total_points * 100) if total_points > 0 else 0, 2)
        )
        attempt.score = score
        attempt.passed = score >= assessment.passing_score
        attempt.finished_at = datetime.now(timezone.utc)

        await db.flush()
        await db.refresh(attempt)

        return AttemptResult(
            attempt_id=attempt.id,
            score=score,
            passed=attempt.passed,
            total_points=total_points,
            earned_points=earned_points,
            answers=answer_results,
        )

    async def get_attempt(
        self, db: AsyncSession, attempt_id: int
    ) -> UserAssessmentAttempt | None:
        r = await db.execute(
            select(UserAssessmentAttempt)
            .where(UserAssessmentAttempt.id == attempt_id)
            .options(selectinload(UserAssessmentAttempt.answers))
        )
        return r.scalar_one_or_none()

    async def get_attempts_by_assessment(
        self,
        db: AsyncSession,
        assessment_id: int,
        user_id: int,
    ) -> Sequence[UserAssessmentAttempt]:
        r = await db.execute(
            select(UserAssessmentAttempt)
            .where(
                UserAssessmentAttempt.assessment_id == assessment_id,
                UserAssessmentAttempt.user_id == user_id,
            )
            .order_by(UserAssessmentAttempt.started_at.desc())
        )
        return r.scalars().all()

    async def has_passed(
        self, db: AsyncSession, assessment_id: int, user_id: int
    ) -> bool:
        r = await db.execute(
            select(UserAssessmentAttempt).where(
                UserAssessmentAttempt.assessment_id == assessment_id,
                UserAssessmentAttempt.user_id == user_id,
                UserAssessmentAttempt.passed == True,
            )
        )
        return r.scalar_one_or_none() is not None

    async def get_course_progress(
        self, db: AsyncSession, user_id: int, course_id: int
    ) -> CourseProgressSummary:
        course = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course.scalar_one_or_none()
        if not course:
            raise ValueError("Curso no encontrado")

        modules = (
            await db.execute(
                select(Module)
                .where(Module.course_id == course_id)
                .order_by(Module.order_index)
            )
        ).scalars().all()

        modules_items: list[ModuleProgressItem] = []
        completed_count = 0

        for mod in modules:
            assessment = await db.execute(
                select(ModuleAssessment).where(
                    ModuleAssessment.module_id == mod.id
                )
            )
            assessment = assessment.scalar_one_or_none()

            total_questions = 0
            attempts_count = 0
            last_score: float | None = None
            passed = False

            if assessment:
                q_count = await db.execute(
                    select(func.count())
                    .select_from(AssessmentQuestion)
                    .where(
                        AssessmentQuestion.assessment_id == assessment.id
                    )
                )
                total_questions = q_count.scalar() or 0

                attempts = (
                    await db.execute(
                        select(UserAssessmentAttempt)
                        .where(
                            UserAssessmentAttempt.assessment_id
                            == assessment.id,
                            UserAssessmentAttempt.user_id == user_id,
                        )
                        .order_by(
                            UserAssessmentAttempt.finished_at.desc().nulls_last()
                        )
                    )
                ).scalars().all()

                attempts_count = len(attempts)
                for att in attempts:
                    if att.passed:
                        passed = True
                    if att.finished_at is not None:
                        if last_score is None:
                            last_score = float(att.score)

            if passed:
                completed_count += 1

            modules_items.append(
                ModuleProgressItem(
                    module_id=mod.id,
                    module_title=mod.title,
                    module_order=mod.order_index,
                    total_assessment_questions=total_questions,
                    attempts_count=attempts_count,
                    last_score=last_score,
                    passed=passed,
                )
            )

        total_modules = len(modules)
        progress_pct = (
            round(completed_count / total_modules * 100, 1)
            if total_modules > 0
            else 0
        )

        return CourseProgressSummary(
            course_id=course.id,
            course_title=course.title,
            total_modules=total_modules,
            completed_modules=completed_count,
            progress_percent=progress_pct,
            modules=modules_items,
        )

    async def get_all_progress(
        self, db: AsyncSession, user_id: int
    ) -> tuple[list[CourseProgressSummary], float]:
        enrollments = (
            await db.execute(
                select(Course)
                .join(
                    Module,
                    Module.course_id == Course.id,
                )
                .join(
                    ModuleAssessment,
                    ModuleAssessment.module_id == Module.id,
                    isouter=True,
                )
                .distinct()
            )
        ).scalars().all()

        course_ids = list({c.id for c in enrollments})
        if not course_ids:
            enrolled = (
                await db.execute(
                    select(Course.id)
                    .join(
                        Module,
                        Module.course_id == Course.id,
                    )
                    .distinct()
                )
            ).scalars().all()
            course_ids = list(enrolled) if enrolled else []

        summaries: list[CourseProgressSummary] = []
        total_completed = 0
        total_modules_all = 0

        for cid in (course_ids or []):
            try:
                summary = await self.get_course_progress(db, user_id, cid)
                summaries.append(summary)
                total_completed += summary.completed_modules
                total_modules_all += summary.total_modules
            except ValueError:
                continue

        overall_pct = (
            round(total_completed / total_modules_all * 100, 1)
            if total_modules_all > 0
            else 0
        )

        return summaries, overall_pct


user_assessment_repository = UserAssessmentRepository()

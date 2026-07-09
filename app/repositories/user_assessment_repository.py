"""Repositorio de intentos y progreso de evaluaciones."""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assessment_option import AssessmentOption
from app.models.assessment_question import AssessmentQuestion
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_task import LessonTask
from app.models.module import Module
from app.models.module_assessment import ModuleAssessment
from app.models.task_submission import TaskSubmission
from app.models.user_assessment_attempt import (
    UserAssessmentAnswer,
    UserAssessmentAttempt,
)
from app.schemas.module_assessment import (
    AnswerResult,
    AttemptResult,
    CourseProgressSummary,
    ModuleProgressItem,
    TaskProgressItem,
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

    async def _get_module_task_progress(
        self, db: AsyncSession, module_id: int, user_id: int
    ) -> tuple[int, int, list[TaskProgressItem]]:
        r = await db.execute(
            select(Lesson).where(Lesson.module_id == module_id)
        )
        lesson_ids = [l.id for l in r.scalars().all()]
        if not lesson_ids:
            return 0, 0, []

        r = await db.execute(
            select(LessonTask).where(LessonTask.lesson_id.in_(lesson_ids))
        )
        tasks = r.scalars().all()
        if not tasks:
            return 0, 0, []

        task_ids = [t.id for t in tasks]
        task_map = {t.id: t for t in tasks}

        r = await db.execute(
            select(TaskSubmission).where(
                TaskSubmission.task_id.in_(task_ids),
                TaskSubmission.user_id == user_id,
            )
        )
        submissions = r.scalars().all()
        submitted_task_ids = {s.task_id for s in submissions}
        sub_map = {s.task_id: s for s in submissions}

        submitted_count = len(submitted_task_ids)
        tasks_detail = [
            TaskProgressItem(
                task_id=t.id,
                task_title=t.title,
                submitted=t.id in submitted_task_ids,
                submission_id=sub_map[t.id].id if t.id in sub_map else None,
                file_url=sub_map[t.id].file_url if t.id in sub_map else None,
                original_filename=sub_map[t.id].original_filename if t.id in sub_map else None,
                submitted_at=sub_map[t.id].submitted_at if t.id in sub_map else None,
            )
            for t in tasks
        ]
        return len(tasks), submitted_count, tasks_detail

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

        # 1. Modules + assessment + questions (1 query)
        r = await db.execute(
            select(Module)
            .where(Module.course_id == course_id)
            .order_by(Module.order_index)
            .options(
                selectinload(Module.assessment)
                .selectinload(ModuleAssessment.questions),
            )
        )
        modules = r.scalars().all()

        # 2. Batch attempts para todos los assessments (1 query)
        assessment_ids = [m.assessment.id for m in modules if m.assessment]
        attempts_map: dict[int, list[UserAssessmentAttempt]] = {}
        if assessment_ids:
            a_r = await db.execute(
                select(UserAssessmentAttempt)
                .where(
                    UserAssessmentAttempt.assessment_id.in_(assessment_ids),
                    UserAssessmentAttempt.user_id == user_id,
                )
                .order_by(UserAssessmentAttempt.finished_at.desc().nulls_last())
            )
            for a in a_r.scalars().all():
                attempts_map.setdefault(a.assessment_id, []).append(a)

        # 3. Task progress para todos los módulos
        task_progress_cache: dict[int, tuple[int, int, list[TaskProgressItem]]] = {}
        for mod in modules:
            tp = await self._get_module_task_progress(db, mod.id, user_id)
            task_progress_cache[mod.id] = tp

        # 4. Construir resultado en Python puro
        modules_items: list[ModuleProgressItem] = []
        completed_count = 0

        for mod in modules:
            assessment = mod.assessment
            total_questions = len(assessment.questions) if assessment else 0
            attempts = attempts_map.get(assessment.id, []) if assessment else []
            attempts_count = len(attempts)
            last_score = float(attempts[0].score) if attempts else None
            passed = any(a.passed for a in attempts)

            total_tasks, submitted_tasks, tasks = task_progress_cache.get(mod.id, (0, 0, []))

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
                    total_tasks=total_tasks,
                    submitted_tasks=submitted_tasks,
                    tasks=tasks,
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
        from app.models.course import CourseEnrollment

        enr_r = await db.execute(
            select(CourseEnrollment.course_id).where(
                CourseEnrollment.user_id == user_id
            )
        )
        enrolled_ids = {row[0] for row in enr_r.all()}
        if not enrolled_ids:
            return [], 0.0

        # 1. Cursos + módulos + assessments + questions (1 query)
        r = await db.execute(
            select(Course)
            .where(Course.id.in_(enrolled_ids))
            .order_by(Course.title)
            .options(
                selectinload(Course.modules)
                .selectinload(Module.assessment)
                .selectinload(ModuleAssessment.questions),
            )
        )
        courses = r.scalars().all()

        # 2. Batch attempts para todos los assessments del usuario (1 query)
        all_assessment_ids = [
            m.assessment.id for c in courses
            for m in c.modules if m.assessment
        ]
        attempts_map: dict[int, list[UserAssessmentAttempt]] = {}
        if all_assessment_ids:
            a_r = await db.execute(
                select(UserAssessmentAttempt)
                .where(
                    UserAssessmentAttempt.assessment_id.in_(all_assessment_ids),
                    UserAssessmentAttempt.user_id == user_id,
                )
                .order_by(UserAssessmentAttempt.finished_at.desc().nulls_last())
            )
            for a in a_r.scalars().all():
                attempts_map.setdefault(a.assessment_id, []).append(a)

        # 3. Task progress para todos los módulos
        task_progress_cache: dict[int, tuple[int, int, list[TaskProgressItem]]] = {}
        for course in courses:
            for mod in course.modules:
                if mod.id not in task_progress_cache:
                    tp = await self._get_module_task_progress(db, mod.id, user_id)
                    task_progress_cache[mod.id] = tp

        # 4. Construir resultado en Python puro
        summaries: list[CourseProgressSummary] = []
        total_completed = 0
        total_modules_all = 0

        for course in courses:
            modules_data: list[ModuleProgressItem] = []
            for mod in course.modules:
                assessment = mod.assessment
                total_questions = len(assessment.questions) if assessment else 0
                attempts = attempts_map.get(assessment.id, []) if assessment else []
                attempts_count = len(attempts)
                last_score = float(attempts[0].score) if attempts else None
                passed = any(a.passed for a in attempts)

                total_tasks, submitted_tasks, tasks = task_progress_cache.get(mod.id, (0, 0, []))

                modules_data.append(
                    ModuleProgressItem(
                        module_id=mod.id,
                        module_title=mod.title,
                        module_order=mod.order_index,
                        total_assessment_questions=total_questions,
                        attempts_count=attempts_count,
                        last_score=last_score,
                        passed=passed,
                        total_tasks=total_tasks,
                        submitted_tasks=submitted_tasks,
                        tasks=tasks,
                    )
                )

            total = len(modules_data)
            completed = sum(1 for m in modules_data if m.passed)
            pct = (completed / total * 100) if total > 0 else 0.0

            summaries.append(
                CourseProgressSummary(
                    course_id=course.id,
                    course_title=course.title,
                    total_modules=total,
                    completed_modules=completed,
                    progress_percent=round(pct, 1),
                    modules=modules_data,
                )
            )
            total_completed += completed
            total_modules_all += total

        overall_pct = (
            round(total_completed / total_modules_all * 100, 1)
            if total_modules_all > 0
            else 0
        )

        return summaries, overall_pct


user_assessment_repository = UserAssessmentRepository()

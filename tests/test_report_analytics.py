"""Analítica: historial de intentos, calificación de tareas y chart."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.tenant import tenant_ctx, resolve_default_tenant_id
from app.models.assessment_question import AssessmentQuestion
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_task import LessonTask
from app.models.module import Module
from app.models.module_assessment import ModuleAssessment
from app.models.task_submission import TaskSubmission
from app.models.user import User
from app.models.user_assessment_attempt import UserAssessmentAttempt


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _default_tenant() -> int:
    async with AsyncSessionLocal() as session:
        return await resolve_default_tenant_id(session)


async def _student_id() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "student@example.com"))
        u = result.scalar_one_or_none()
        if u is None:
            from app.core.security import get_password_hash

            u = User(
                email="student@example.com",
                password_hash=get_password_hash("StudentPass123!"),
                name="Estudiante",
                first_last_name="Prueba",
                role="student",
                identity_type="CC",
                identity_number="1010101010",
                phone_number="+570000000011",
                is_active=True,
                tenant_id=await _default_tenant(),
            )
            session.add(u)
            await session.commit()
            await session.refresh(u)
        return u.id


async def _teacher_id() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "teacher@example.com"))
        return result.scalar_one().id


@pytest.mark.asyncio
async def test_catalog_includes_chart(client, superuser_token):
    resp = await client.get("/api/v1/reports", headers=hdr(superuser_token))
    assert resp.status_code == 200
    for item in resp.json():
        assert isinstance(item.get("chart"), dict)
    keys = [i["key"] for i in resp.json()]
    assert "assessment_attempts_history" in keys
    assert "task_grades" in keys


@pytest.mark.asyncio
async def test_assessment_attempts_history(client, superuser_token):
    tid = await _default_tenant()
    sid = await _student_id()
    async with AsyncSessionLocal() as session:
        async with tenant_ctx(tid):
            course = Course(title="Curso Evaluaciones", status="published")
            session.add(course)
            await session.flush()
            module = Module(course_id=course.id, title="Mod 1", order_index=0)
            session.add(module)
            await session.flush()
            assessment = ModuleAssessment(module_id=module.id, passing_score=70)
            session.add(assessment)
            await session.flush()
            base = datetime(2026, 10, 1, tzinfo=UTC)
            session.add_all([
                UserAssessmentAttempt(assessment_id=assessment.id, user_id=sid, score=55, passed=False, started_at=base, finished_at=base + timedelta(minutes=10)),
                UserAssessmentAttempt(assessment_id=assessment.id, user_id=sid, score=85, passed=True, started_at=base + timedelta(hours=1), finished_at=base + timedelta(hours=1, minutes=12)),
            ])
            await session.commit()

    resp = await client.get(
        "/api/v1/reports/assessment_attempts_history", headers=hdr(superuser_token)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    by_attempt = {r["intento"]: r["nota"] for r in rows if r["curso"] == "Curso Evaluaciones"}
    assert by_attempt.get(1) == 55
    assert by_attempt.get(2) == 85


@pytest.mark.asyncio
async def test_task_grade_flow(client, teacher_token, superuser_token):
    tid = await _default_tenant()
    sid = await _student_id()
    teacher_id = await _teacher_id()

    async with AsyncSessionLocal() as session:
        async with tenant_ctx(tid):
            course = Course(title="Curso Tareas", status="published", teacher_id=teacher_id)
            session.add(course)
            await session.flush()
            module = Module(course_id=course.id, title="Mod", order_index=0)
            session.add(module)
            await session.flush()
            lesson = Lesson(module_id=module.id, title="Lección 1", order_index=0)
            session.add(lesson)
            await session.flush()
            task = LessonTask(lesson_id=lesson.id, title="Tarea 1", order_index=0)
            session.add(task)
            await session.flush()
            sub = TaskSubmission(
                task_id=task.id,
                user_id=sid,
                file_url="tasks/files/x.pdf",
                original_filename="x.pdf",
                mime_type="application/pdf",
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            submission_id = sub.id

    grade = await client.patch(
        f"/api/v1/submissions/{submission_id}/grade",
        headers=hdr(teacher_token),
        json={"score": 82.5, "feedback": "Muy buen trabajo"},
    )
    assert grade.status_code == 200, grade.text
    body = grade.json()
    assert float(body["score"]) == 82.5
    assert body["passed"] is True
    assert body["feedback"] == "Muy buen trabajo"
    assert body["graded_by"] == teacher_id

    report = await client.get("/api/v1/reports/task_grades", headers=hdr(superuser_token))
    assert report.status_code == 200, report.text
    payload = report.json()
    assert "modulo" in {c["key"] for c in payload["columns"]}
    rows = payload["rows"]
    assert any(r["tarea"] == "Tarea 1" and float(r["nota"]) == 82.5 for r in rows)
    assert any(r.get("modulo") == "Mod" for r in rows)


@pytest.mark.asyncio
async def test_teacher_cannot_grade_foreign_course(client, superuser_token, teacher_token):
    """El teacher solo califica entregas de sus cursos."""
    tid = await _default_tenant()
    sid = await _student_id()
    async with AsyncSessionLocal() as session:
        async with tenant_ctx(tid):
            course = Course(title="Curso No Mio", status="published", teacher_id=None)
            session.add(course)
            await session.flush()
            module = Module(course_id=course.id, title="M", order_index=0)
            session.add(module)
            await session.flush()
            lesson = Lesson(module_id=module.id, title="L", order_index=0)
            session.add(lesson)
            await session.flush()
            task = LessonTask(lesson_id=lesson.id, title="T", order_index=0)
            session.add(task)
            await session.flush()
            sub = TaskSubmission(task_id=task.id, user_id=sid, file_url="u", original_filename="u", mime_type="application/pdf")
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            submission_id = sub.id

    resp = await client.patch(
        f"/api/v1/submissions/{submission_id}/grade",
        headers=hdr(teacher_token),
        json={"score": 90, "feedback": ""},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_progress_requires_tasks_and_assessment(client, student_token):
    """Un módulo solo se completa si se aprobó la evaluación Y se entregaron las tareas."""
    tid = await _default_tenant()
    sid = await _student_id()
    async with AsyncSessionLocal() as session:
        async with tenant_ctx(tid):
            course = Course(title="Curso Progreso", status="published")
            session.add(course)
            await session.flush()
            module = Module(course_id=course.id, title="Mod Progreso", order_index=0)
            session.add(module)
            await session.flush()
            assessment = ModuleAssessment(module_id=module.id, passing_score=70)
            session.add(assessment)
            await session.flush()
            session.add(
                AssessmentQuestion(
                    assessment_id=assessment.id,
                    question_text="¿Pregunta?",
                    question_type="multiple_choice",
                )
            )
            lesson = Lesson(module_id=module.id, title="Lección P", order_index=0)
            session.add(lesson)
            await session.flush()
            task = LessonTask(lesson_id=lesson.id, title="Tarea P", order_index=0)
            session.add(task)
            await session.flush()
            base = datetime(2026, 10, 1, tzinfo=UTC)
            session.add(
                UserAssessmentAttempt(
                    assessment_id=assessment.id,
                    user_id=sid,
                    score=90,
                    passed=True,
                    started_at=base,
                    finished_at=base + timedelta(minutes=5),
                )
            )
            await session.commit()
            course_id = course.id
            task_id = task.id

    resp = await client.get(
        f"/api/v1/user-progress/summary/{course_id}", headers=hdr(student_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["progress_percent"] == 0
    assert body["completed_modules"] == 0

    async with AsyncSessionLocal() as session:
        async with tenant_ctx(tid):
            session.add(
                TaskSubmission(
                    task_id=task_id,
                    user_id=sid,
                    file_url="tasks/files/p.pdf",
                    original_filename="p.pdf",
                    mime_type="application/pdf",
                )
            )
            await session.commit()

    resp2 = await client.get(
        f"/api/v1/user-progress/summary/{course_id}", headers=hdr(student_token)
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["progress_percent"] == 100
    assert body2["completed_modules"] == 1
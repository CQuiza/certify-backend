"""Ciclo de vida de renovación automática de certificados."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.certificate import Certificate
from app.models.certificate_type import CertificateType
from app.models.course import Course, CourseEnrollment
from app.models.lesson import Lesson
from app.models.lesson_task import LessonTask
from app.models.module import Module
from app.models.payment import CourseOrder, CourseOrderItem
from app.models.pending_certificate import PendingCertificate
from app.models.progress import UserProgress
from app.models.task_submission import TaskSubmission
from app.models.user import User
from app.services import payment_service as ps
from app.services.certificate_lifecycle import certificate_lifecycle
from app.services.certificate_storage import CertificateStorageService


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _student_id(db) -> int:
    r = await db.execute(select(User).where(User.email == "student@example.com"))
    u = r.scalar_one_or_none()
    if u is None:
        from app.core.security import get_password_hash

        u = User(
            email="student@example.com",
            password_hash=get_password_hash("StudentPass1!"),
            name="Estudiante",
            first_last_name="Prueba",
            role="student",
            identity_type="CC",
            identity_number="1010101010",
            phone_number="+570000000011",
            is_active=True,
        )
        db.add(u)
        await db.flush()
    return u.id


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.email == "super@example.com"))).scalar_one()


async def _build_course(db, *, title, price=0, renewal_price=None, with_task=True, cert_type=None):
    course = Course(title=title, status="published", price=price, renewal_price=renewal_price, is_for_sale=True)
    if cert_type is not None:
        course.certificate_type_id = cert_type.id
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="M", order_index=0)
    db.add(module)
    await db.flush()
    lesson = Lesson(module_id=module.id, title="L", order_index=0)
    db.add(lesson)
    await db.flush()
    task = None
    if with_task:
        task = LessonTask(lesson_id=lesson.id, title="T", order_index=0)
        db.add(task)
        await db.flush()
    return course, lesson, task


async def _make_expired_cert(db, *, user_id, course_id, cert_type_id=None):
    cert = Certificate(
        unique_id=uuid.uuid4(),
        certificate_type_id=cert_type_id,
        course_id=course_id,
        user_id=user_id,
        issued_at=datetime.now(UTC) - timedelta(days=400),
        expires_at=datetime.now(UTC) - timedelta(days=1),
        status="expired",
    )
    db.add(cert)
    await db.flush()
    return cert


@pytest.mark.asyncio
async def test_expired_worker_marks_expired_and_unenrolls(db, monkeypatch):
    from app.workers import tasks as tasks_mod

    student_id = await _student_id(db)
    course, _, _ = await _build_course(db, title="Curso Worker", with_task=False)
    db.add(CourseEnrollment(user_id=student_id, course_id=course.id))
    cert = Certificate(
        unique_id=uuid.uuid4(),
        course_id=course.id,
        user_id=student_id,
        issued_at=datetime.now(UTC) - timedelta(days=400),
        expires_at=datetime.now(UTC) - timedelta(days=2),
        status="active",
    )
    db.add(cert)
    await db.commit()
    cert_id = cert.id

    async def _dl(*a, **k):
        return b""

    async def _up(*a, **k):
        return None

    monkeypatch.setattr(CertificateStorageService, "download_pdf", _dl)
    monkeypatch.setattr(CertificateStorageService, "upload_pdf", _up)

    await tasks_mod._async_check_expired_certificates()

    async with AsyncSessionLocal() as s:
        c = (await s.execute(select(Certificate).where(Certificate.id == cert_id))).scalar_one()
        assert c.status == "expired"
        enr = (
            await s.execute(
                select(CourseEnrollment).where(
                    CourseEnrollment.user_id == student_id, CourseEnrollment.course_id == course.id
                )
            )
        ).scalars().all()
        assert enr == []


@pytest.mark.asyncio
async def test_start_renewal_reassigns_and_resets(db):
    student_id = await _student_id(db)
    admin = await _admin(db)
    course, lesson, task = await _build_course(db, title="Curso Renovar")
    cert = await _make_expired_cert(db, user_id=student_id, course_id=course.id)
    # progreso y entrega previos
    db.add(UserProgress(user_id=student_id, lesson_id=lesson.id, completed=True))
    db.add(TaskSubmission(task_id=task.id, user_id=student_id, file_url="x", original_filename="x.pdf", mime_type="application/pdf"))
    await db.flush()

    pc = await certificate_lifecycle.start_renewal(db, admin=admin, cert=cert)
    await db.commit()

    assert pc.renewal_of_certificate_id == cert.id
    assert pc.status == "in_progress"

    enr = (
        await db.execute(
            select(CourseEnrollment).where(
                CourseEnrollment.user_id == student_id, CourseEnrollment.course_id == course.id
            )
        )
    ).scalar_one_or_none()
    assert enr is not None
    prog = (
        await db.execute(select(UserProgress).where(UserProgress.user_id == student_id, UserProgress.lesson_id == lesson.id))
    ).scalars().all()
    subs = (
        await db.execute(select(TaskSubmission).where(TaskSubmission.user_id == student_id, TaskSubmission.task_id == task.id))
    ).scalars().all()
    assert prog == [] and subs == []


@pytest.mark.asyncio
async def test_self_service_free_renewal(client, student_token, db):
    me = await client.get("/api/v1/auth/me", headers=hdr(student_token))
    student_id = me.json()["id"]
    course, _, _ = await _build_course(db, title="Curso Gratis Renov", price=0, renewal_price=0, with_task=False)
    cert = await _make_expired_cert(db, user_id=student_id, course_id=course.id)
    await db.commit()

    resp = await client.post(f"/api/v1/payments/renew/{cert.id}", headers=hdr(student_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["free"] is True

    async with AsyncSessionLocal() as s:
        pc = (
            await s.execute(
                select(PendingCertificate).where(
                    PendingCertificate.user_id == student_id, PendingCertificate.course_id == course.id
                )
            )
        ).scalar_one_or_none()
        assert pc is not None and pc.renewal_of_certificate_id == cert.id


@pytest.mark.asyncio
async def test_paid_renewal_order_and_approval(client, superuser_token, student_token, db, monkeypatch):
    import app.api.v1.endpoints.payments as payments_mod

    me = await client.get("/api/v1/auth/me", headers=hdr(student_token))
    student_id = me.json()["id"]
    course, _, _ = await _build_course(db, title="Curso Pago Renov", price=50000, renewal_price=None, with_task=False)
    cert = await _make_expired_cert(db, user_id=student_id, course_id=course.id)
    await db.commit()

    monkeypatch.setattr(payments_mod, "payments_configured", lambda: True)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    async def fake_pref(db_, order, base_url, api_prefix):
        return "https://init.mp/renew", "PREF_R"

    monkeypatch.setattr(payments_mod, "create_preference", fake_pref)

    resp = await client.post(f"/api/v1/payments/renew/{cert.id}", headers=hdr(student_token))
    assert resp.status_code == 200, resp.text
    order_id = resp.json()["order_id"]
    assert resp.json()["init_point"] == "https://init.mp/renew"

    order = (await db.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
    assert order.kind == "renewal" and order.renewal_certificate_id == cert.id

    # Aprobación (server-to-server)
    result = await ps.process_payment(
        db,
        {"id": "PAY_R", "status": "approved", "external_reference": order.order_no, "date_approved": "2026-10-13T12:00:00-04:00"},
    )
    await db.commit()
    assert result.status == "approved"

    async with AsyncSessionLocal() as s:
        enr = (
            await s.execute(
                select(CourseEnrollment).where(
                    CourseEnrollment.user_id == student_id, CourseEnrollment.course_id == course.id
                )
            )
        ).scalar_one_or_none()
        assert enr is not None
        pc = (
            await s.execute(
                select(PendingCertificate).where(
                    PendingCertificate.user_id == student_id, PendingCertificate.course_id == course.id
                )
            )
        ).scalar_one_or_none()
        assert pc is not None and pc.renewal_of_certificate_id == cert.id


@pytest.mark.asyncio
async def test_completion_renews_same_certificate(db, monkeypatch):
    student_id = await _student_id(db)
    admin = await _admin(db)
    ct = CertificateType(name="Tipo Renov", type="basic", hours=10, validity_type="years", validity_value=1)
    db.add(ct)
    await db.flush()
    course, lesson, task = await _build_course(db, title="Curso Completa Renov", cert_type=ct)
    cert = await _make_expired_cert(db, user_id=student_id, course_id=course.id, cert_type_id=ct.id)
    await db.flush()
    original_uuid = cert.unique_id

    # Inicia renovación (reasigna + resetea)
    await certificate_lifecycle.start_renewal(db, admin=admin, cert=cert)
    await db.flush()

    # El estudiante completa: entrega la única tarea.
    db.add(TaskSubmission(task_id=task.id, user_id=student_id, file_url="x", original_filename="x.pdf", mime_type="application/pdf"))
    await db.flush()

    async def _up(*a, **k):
        return None

    monkeypatch.setattr(CertificateStorageService, "upload_pdf", _up)

    issued = await certificate_lifecycle.maybe_issue_pending(db, user_id=student_id, course_id=course.id)
    await db.commit()
    assert issued == 1

    refreshed = (await db.execute(select(Certificate).where(Certificate.id == cert.id))).scalar_one()
    assert refreshed.status == "active"
    assert refreshed.unique_id == original_uuid
    exp = refreshed.expires_at
    assert exp is not None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    assert exp > datetime.now(UTC)
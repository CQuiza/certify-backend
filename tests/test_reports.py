"""Reportes analíticos y relación de admins del dashboard."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.certificate import Certificate
from app.models.certificate_audit import CertificateAudit
from app.models.certificate_type import CertificateType
from app.models.course import Course, CourseEnrollment
from app.models.user import User


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_reports_catalog_and_rbac(client, superuser_token, student_token, teacher_token):
    ok = await client.get("/api/v1/reports", headers=hdr(superuser_token))
    assert ok.status_code == 200
    keys = [r["key"] for r in ok.json()]
    assert "certificates_by_admin" in keys
    assert "activity_monthly" in keys

    assert (await client.get("/api/v1/reports", headers=hdr(student_token))).status_code == 403
    assert (await client.get("/api/v1/reports", headers=hdr(teacher_token))).status_code == 403


@pytest.mark.asyncio
async def test_users_by_role_report(client, superuser_token):
    resp = await client.get("/api/v1/reports/users_by_role", headers=hdr(superuser_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    roles = {r["rol"]: r["cantidad"] for r in body["rows"]}
    assert "superuser" in roles
    assert "student" in roles


@pytest.mark.asyncio
async def test_certificates_by_admin_report(client, superuser_token):
    from app.core.tenant import tenant_ctx

    async with AsyncSessionLocal() as session:
        from app.core.tenant import resolve_default_tenant_id

        tenant_id = await resolve_default_tenant_id(session)
        async with tenant_ctx(tenant_id):
            # estudiante
            student = await session.execute(select(User).where(User.email == "student@example.com"))
            student = student.scalar_one_or_none()
            if student is None:
                from app.core.security import get_password_hash

                student = User(
                    email="student@example.com",
                    password_hash=get_password_hash("StudentPass123!"),
                    name="Estudiante",
                    first_last_name="Prueba",
                    role="student",
                    identity_type="CC",
                    identity_number="1010101010",
                    phone_number="+570000000011",
                    is_active=True,
                    tenant_id=tenant_id,
                )
                session.add(student)
                await session.flush()

            admin = (
                await session.execute(select(User).where(User.email == "super@example.com"))
            ).scalar_one()

            ctype = CertificateType(
                name="Diploma Integral",
                type="diploma",
                hours=40,
                validity_type="years",
                validity_value=1,
                created_by=admin.id,
            )
            session.add(ctype)
            await session.flush()

            cert = Certificate(
                unique_id=uuid.uuid4(),
                certificate_type_id=ctype.id,
                user_id=student.id,
                issued_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=365),
                status="active",
            )
            session.add(cert)
            await session.flush()

            session.add(
                CertificateAudit(
                    certificate_id=cert.id,
                    certificate_unique_id=cert.unique_id,
                    action="issued",
                    performed_by=admin.id,
                )
            )
            await session.commit()

    resp = await client.get(
        "/api/v1/reports/certificates_by_admin", headers=hdr(superuser_token)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert any(r["tipo"] == "diploma" and r["admin_email"] == "super@example.com" for r in rows)


@pytest.mark.asyncio
async def test_courses_assigned_report(client, superuser_token, teacher_token):
    from app.core.tenant import tenant_ctx, resolve_default_tenant_id

    async with AsyncSessionLocal() as session:
        tenant_id = await resolve_default_tenant_id(session)
        async with tenant_ctx(tenant_id):
            student = (
                await session.execute(select(User).where(User.email == "student@example.com"))
            ).scalar_one()
            course = Course(title="Curso Asignado", description="x", status="published", teacher_id=3)
            session.add(course)
            await session.flush()
            session.add(CourseEnrollment(user_id=student.id, course_id=course.id))
            await session.commit()

    resp = await client.get(
        "/api/v1/reports/courses_assigned_by_user", headers=hdr(superuser_token)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert any("Curso Asignado" in (r["cursos"] or "") for r in rows)


@pytest.mark.asyncio
async def test_report_csv_format(client, superuser_token):
    resp = await client.get(
        "/api/v1/reports/users_by_role",
        headers=hdr(superuser_token),
        params={"format": "csv"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Rol" in resp.text


@pytest.mark.asyncio
async def test_dashboard_admins_card(client, superuser_token):
    resp = await client.get("/api/v1/dashboard/admins", headers=hdr(superuser_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    super_row = next((a for a in body if a["email"] == "super@example.com"), None)
    assert super_row is not None
    assert {"id", "name", "email", "identity_number", "phone_number"}.issubset(super_row)


@pytest.mark.asyncio
async def test_admins_card_rbac(client, student_token, teacher_token):
    assert (await client.get("/api/v1/dashboard/admins", headers=hdr(student_token))).status_code == 403
    assert (await client.get("/api/v1/dashboard/admins", headers=hdr(teacher_token))).status_code == 403
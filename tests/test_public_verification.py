"""Verificación pública mínima por identidad."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import get_password_hash
from app.models.certificate import Certificate
from app.models.certificate_type import CertificateType
from app.models.course import Course
from app.models.user import User


@pytest.mark.asyncio
async def test_public_search_only_returns_minimal_data(client, db):
    suffix = uuid.uuid4().hex[:8]
    identity = f"PUB-{suffix}"
    email = f"public-{suffix}@example.com"

    student = User(
        email=email,
        password_hash=get_password_hash("StudentPass1!"),
        name="Estudiante Público",
        first_last_name="Prueba",
        role="student",
        identity_type="CC",
        identity_number=identity,
        phone_number=f"+57{suffix[:8]}",
        is_active=True,
    )
    db.add(student)
    await db.flush()

    cert_type = CertificateType(
        name="Diplomado Público",
        type="diploma",
        hours=40,
        validity_type="years",
        validity_value=1,
        created_by=student.id,
    )
    db.add(cert_type)
    await db.flush()

    course = Course(
        title="Curso Público",
        status="published",
        certificate_type_id=cert_type.id,
    )
    db.add(course)
    await db.flush()

    uid = uuid.uuid4()
    cert = Certificate(
        unique_id=uid,
        certificate_type_id=cert_type.id,
        course_id=course.id,
        user_id=student.id,
        issued_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=365),
        status="active",
        pdf_url=f"https://example.test/api/v1/certificates/view/{uid}",
    )
    db.add(cert)
    await db.commit()

    resp = await client.get(f"/api/v1/certificates/search-by-identity/{identity}")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert len(data) == 1
    assert set(data[0].keys()) == {"user_name", "identity_number", "certificates"}
    assert data[0]["user_name"] == "Estudiante Público"
    assert data[0]["identity_number"] == identity

    item = data[0]["certificates"][0]
    assert set(item.keys()) == {
        "course_title",
        "status",
        "issued_at",
        "expires_at",
        "pdf_url",
    }
    assert item["course_title"] == "Curso Público"
    assert item["status"] == "active"
    assert item["pdf_url"] is not None
    assert "unique_id" not in item
    assert "user_id" not in item
    assert "certificate_type_id" not in item
    assert "course_id" not in item
    assert "qr_code_url" not in item

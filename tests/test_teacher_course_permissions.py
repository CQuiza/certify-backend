"""Permisos del teacher sobre cursos (crear/editar/eliminar/inscribir) y
orden descendente (último creado primero)."""

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ids(items) -> list[int]:
    return [x["id"] for x in items]


async def _student_id() -> int:
    """Devuelve (creando si falta) un estudiante del tenant default."""
    from app.core.security import get_password_hash
    from app.core.tenant import resolve_default_tenant_id
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "student@example.com"))
        row = result.scalar_one_or_none()
        if row is not None:
            return row.id
        tenant_id = await resolve_default_tenant_id(session)
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
            tenant_id=tenant_id,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


@pytest.mark.asyncio
async def test_teacher_can_create_course(client, superuser_token, teacher_token):
    resp = await client.post(
        "/api/v1/courses",
        headers=hdr(teacher_token),
        json={"title": "Curso del Docente", "description": "x", "status": "draft"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    me = await client.get("/api/v1/auth/me", headers=hdr(teacher_token))
    assert me.status_code == 200
    assert body["teacher_id"] == me.json()["id"]


@pytest.mark.asyncio
async def test_teacher_cannot_edit_foreign_course(client, superuser_token, teacher_token):
    # Superuser crea un curso asignado a OTRO docente (sin docente).
    created = await client.post(
        "/api/v1/courses",
        headers=hdr(superuser_token),
        json={"title": "Curso Ajeno", "description": "x", "status": "draft"},
    )
    course_id = created.json()["id"]

    patch = await client.patch(
        f"/api/v1/courses/{course_id}",
        headers=hdr(teacher_token),
        json={"description": "intento de edición"},
    )
    assert patch.status_code == 403

    delete = await client.delete(f"/api/v1/courses/{course_id}", headers=hdr(teacher_token))
    assert delete.status_code == 403


@pytest.mark.asyncio
async def test_teacher_can_edit_and_delete_own_course(client, teacher_token):
    created = await client.post(
        "/api/v1/courses",
        headers=hdr(teacher_token),
        json={"title": "Curso Propio", "description": "x", "status": "draft"},
    )
    course_id = created.json()["id"]
    patch = await client.patch(
        f"/api/v1/courses/{course_id}",
        headers=hdr(teacher_token),
        json={"description": "editado"},
    )
    assert patch.status_code == 200
    assert patch.json()["description"] == "editado"

    delete = await client.delete(f"/api/v1/courses/{course_id}", headers=hdr(teacher_token))
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_teacher_enroll_student_in_own_course(client, teacher_token):
    created = await client.post(
        "/api/v1/courses",
        headers=hdr(teacher_token),
        json={"title": "Curso con Estudiantes", "description": "x", "status": "published"},
    )
    course_id = created.json()["id"]
    sid = await _student_id()

    resp = await client.post(
        "/api/v1/course-enrollments",
        headers=hdr(teacher_token),
        json={"user_id": sid, "course_id": course_id},
    )
    assert resp.status_code == 201, resp.text

    # Desinscribir
    del_resp = await client.delete(
        f"/api/v1/course-enrollments/{resp.json()['id']}", headers=hdr(teacher_token)
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_teacher_cannot_enroll_in_foreign_course(client, superuser_token, teacher_token):
    created = await client.post(
        "/api/v1/courses",
        headers=hdr(superuser_token),
        json={"title": "Curso No Mio", "description": "x", "status": "published"},
    )
    course_id = created.json()["id"]
    sid = await _student_id()

    resp = await client.post(
        "/api/v1/course-enrollments",
        headers=hdr(teacher_token),
        json={"user_id": sid, "course_id": course_id},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_courses_ordered_desc(client, superuser_token):
    await client.post("/api/v1/courses", headers=hdr(superuser_token), json={"title": "Order A", "description": "", "status": "draft"})
    await client.post("/api/v1/courses", headers=hdr(superuser_token), json={"title": "Order B", "description": "", "status": "draft"})

    resp = await client.get("/api/v1/courses", headers=hdr(superuser_token), params={"limit": 100})
    assert resp.status_code == 200
    ids = _ids(resp.json())
    assert ids == sorted(ids, reverse=True), "los cursos deben venir del más reciente al más antiguo"


@pytest.mark.asyncio
async def test_users_ordered_desc(client, superuser_token):
    """Usuarios sembrados directo (sin correo de background) + orden desc."""
    from app.core.security import get_password_hash
    from app.core.tenant import resolve_default_tenant_id
    from app.repositories.user_repository import user_repository

    async with AsyncSessionLocal() as session:
        tenant_id = await resolve_default_tenant_id(session)
        await user_repository.create(
            session,
            email="order1@example.com",
            password_hash=get_password_hash("OrderPass123!"),
            name="Uno",
            first_last_name="Orden",
            role="student",
            identity_type="CC",
            identity_number="880000001",
            phone_number="+570000000081",
            is_active=True,
            tenant_id=tenant_id,
        )
        await user_repository.create(
            session,
            email="order2@example.com",
            password_hash=get_password_hash("OrderPass123!"),
            name="Dos",
            first_last_name="Orden",
            role="student",
            identity_type="CC",
            identity_number="880000002",
            phone_number="+570000000082",
            is_active=True,
            tenant_id=tenant_id,
        )
        await session.commit()

    resp = await client.get("/api/v1/users", headers=hdr(superuser_token), params={"limit": 100})
    assert resp.status_code == 200
    ids = _ids(resp.json()["items"])
    assert ids == sorted(ids, reverse=True), "los usuarios deben venir del más reciente al más antiguo"
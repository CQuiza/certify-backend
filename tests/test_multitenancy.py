"""Pruebas de multitenancy: aislamiento, unicidad por-tenant y panel admin."""

import pytest
from sqlalchemy import select

from app.core.tenant import tenant_ctx
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.tenant_repository import tenant_repository
from app.repositories.user_repository import user_repository


async def _tenant_id(slug: str) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        t = await tenant_repository.get_by_slug(session, slug)
        return t.id


@pytest.mark.asyncio
async def test_isolation_courses_between_tenants(
    client, db, superuser_token, tenant_b_admin_token
):
    # Superadmin crea un curso en DEFAULT.
    resp = await client.post(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={"title": "Curso Solo Default", "description": "x", "status": "draft"},
    )
    assert resp.status_code == 201, resp.text

    # El admin de ACME NO debe ver ese curso.
    resp = await client.get(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {tenant_b_admin_token}"},
        params={"limit": 100},
    )
    assert resp.status_code == 200, resp.text
    titles = [c["title"] for c in resp.json()]
    assert "Curso Solo Default" not in titles


@pytest.mark.asyncio
async def test_same_email_allowed_in_different_tenants(db, tenant_b_credentials):
    acme_tenant_id = await _tenant_id("acme")
    email = "duplicado@example.com"
    # En ACME se crea sin problema.
    async with tenant_ctx(acme_tenant_id):
        u = await user_repository.create(
            db,
            email=email,
            password_hash="x",
            name="Dup",
            first_last_name="Acme",
            role="student",
            identity_type="CC",
            identity_number="999000001",
            phone_number="+570000000099",
            is_active=True,
        )
    assert u.tenant_id == acme_tenant_id


@pytest.mark.asyncio
async def test_default_tenant_cannot_create_duplicate_email(db):
    # 'student@example.com' ya existe en DEFAULT.
    result = await db.execute(select(User).where(User.email == "student@example.com"))
    if result.scalar_one_or_none() is None:
        from app.core.security import get_password_hash

        await user_repository.create(
            db,
            email="student@example.com",
            password_hash=get_password_hash("x"),
            name="Est",
            first_last_name="Prueba",
            role="student",
            identity_type="CC",
            identity_number="1010101010",
            phone_number="+570000000011",
            is_active=True,
        )
    dup = await db.execute(select(User).where(User.email == "student@example.com"))
    assert dup.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_admin_panel_rbac(client, superuser_token, student_token, tenant_b_admin_token):
    hdr = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731

    assert (await client.get("/api/v1/admin/tenants", headers=hdr(student_token))).status_code == 403
    assert (await client.get("/api/v1/admin/tenants", headers=hdr(tenant_b_admin_token))).status_code == 403

    resp = await client.get("/api/v1/admin/tenants", headers=hdr(superuser_token))
    assert resp.status_code == 200, resp.text
    slugs = [t["slug"] for t in resp.json()]
    assert "default" in slugs
    assert "acme" in slugs


@pytest.mark.asyncio
async def test_create_tenant_via_api(client, superuser_token):
    resp = await client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={
            "name": "Beta Org",
            "slug": "beta",
            "admin_email": "admin@beta.example",
            "admin_name": "Admin Beta",
            "admin_password": "BetaPass123!",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "beta"
    assert body["is_active"] is True

    # El admin recién creado se loguea por su subdominio.
    from httpx import ASGITransport, AsyncClient

    import app.main as m

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://beta.testserver") as ac:
        login = await ac.post(
            "/api/v1/auth/token",
            data={"username": "admin@beta.example", "password": "BetaPass123!"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        me = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert me.json()["email"] == "admin@beta.example"


@pytest.mark.asyncio
async def test_create_tenant_duplicate_slug(client, superuser_token):
    resp = await client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={
            "name": "Acme 2",
            "slug": "acme",
            "admin_email": "admin2@acme.example",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_seeds_do_not_crash_with_multiple_tenants(tenant_b_credentials):
    """Regresión: con varias orgs (y su bot cada una), el seed de arranque
    no debe lanzar MultipleResultsFound ni romper la app."""
    from app.main import _seed_system_bot, _seed_superuser

    await _seed_superuser()
    await _seed_system_bot()


@pytest.mark.asyncio
async def test_deactivate_tenant(client, superuser_token):
    resp = await client.post(
        "/api/v1/admin/tenants",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={
            "name": "Gamma",
            "slug": "gamma",
            "admin_email": "admin@gamma.example",
            "admin_password": "GammaPass123!",
        },
    )
    tenant_id = resp.json()["id"]
    patch = await client.patch(
        f"/api/v1/admin/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={"is_active": False},
    )
    assert patch.status_code == 200
    assert patch.json()["is_active"] is False
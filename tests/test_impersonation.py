"""Impersonación del superuser dentro de cualquier tenant ('Ver como')."""

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.tenant import Tenant


def hdr(token: str, acting: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if acting is not None:
        h["X-Acting-Tenant"] = acting
    return h


async def _acme_id() -> int:
    async with AsyncSessionLocal() as session:
        t = await session.execute(select(Tenant).where(Tenant.slug == "acme"))
        return t.scalar_one().id


@pytest.mark.asyncio
async def test_superuser_impersonates_tenant(client, superuser_token, tenant_b_credentials):
    acme_id = await _acme_id()

    imp = await client.post(
        f"/api/v1/admin/tenants/{acme_id}/impersonate", headers=hdr(superuser_token)
    )
    assert imp.status_code == 200, imp.text

    # Con el header X-Acting-Tenant, el scope será acme.
    acting_headers = hdr(superuser_token, str(acme_id))
    admins = await client.get("/api/v1/dashboard/admins", headers=acting_headers)
    assert admins.status_code == 200, admins.text
    emails = [a["email"] for a in admins.json()]
    assert "admin@acme.example" in emails
    assert "super@example.com" not in emails

    acting = await client.get("/api/v1/admin/tenants/acting", headers=acting_headers)
    assert acting.status_code == 200
    assert acting.json()["slug"] == "acme"


@pytest.mark.asyncio
async def test_non_superuser_cannot_impersonate(client, student_token, tenant_b_credentials):
    acme_id = await _acme_id()
    resp = await client.post(
        f"/api/v1/admin/tenants/{acme_id}/impersonate", headers=hdr(student_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_stop_restores_default_scope(client, superuser_token, tenant_b_credentials):
    acme_id = await _acme_id()

    admins = await client.get(
        "/api/v1/dashboard/admins", headers=hdr(superuser_token, str(acme_id))
    )
    assert "admin@acme.example" in [a["email"] for a in admins.json()]

    stop = await client.post("/api/v1/admin/tenants/stop", headers=hdr(superuser_token, str(acme_id)))
    assert stop.status_code == 200

    # Sin header acting, el scope vuelve al tenant de la sesión (default).
    admins = await client.get("/api/v1/dashboard/admins", headers=hdr(superuser_token))
    emails = [a["email"] for a in admins.json()]
    assert "super@example.com" in emails


@pytest.mark.asyncio
async def test_acting_null_without_impersonation(client, superuser_token):
    acting = await client.get("/api/v1/admin/tenants/acting", headers=hdr(superuser_token))
    assert acting.status_code == 200
    assert acting.json()["tenant_id"] is None


@pytest.mark.asyncio
async def test_non_superuser_header_ignored(client, student_token, tenant_b_credentials):
    acme_id = await _acme_id()
    admins = await client.get("/api/v1/dashboard/admins", headers=hdr(student_token, str(acme_id)))
    # El estudiante ni siquiera tiene acceso al endpoint (403).
    assert admins.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_list_acting(client, tenant_b_admin_token):
    resp = await client.get(
        "/api/v1/admin/tenants/acting", headers=hdr(tenant_b_admin_token)
    )
    assert resp.status_code == 403
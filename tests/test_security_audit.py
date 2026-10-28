"""Auditoría de acciones privilegiadas y acceso restringido."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_impersonation_is_audited_for_superuser_only(
    superuser_token, tenant_b_admin_token
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        tenants = await ac.get("/api/v1/admin/tenants", headers=hdr(superuser_token))
        assert tenants.status_code == 200, tenants.text
        acme = next(t for t in tenants.json() if t["slug"] == "acme")

        started = await ac.post(
            f"/api/v1/admin/tenants/{acme['id']}/impersonate",
            headers=hdr(superuser_token),
        )
        assert started.status_code == 200, started.text

        audit = await ac.get(
            "/api/v1/admin/security-audit",
            headers=hdr(superuser_token),
            params={"action": "impersonation_started", "target_tenant_id": acme["id"]},
        )
        assert audit.status_code == 200, audit.text
        rows = audit.json()["items"]
        assert any(row["action"] == "impersonation_started" for row in rows)
        assert any(row["target_tenant_id"] == acme["id"] for row in rows)

        forbidden = await ac.get(
            "/api/v1/admin/security-audit", headers=hdr(tenant_b_admin_token)
        )
        assert forbidden.status_code == 403

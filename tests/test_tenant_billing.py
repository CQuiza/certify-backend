"""Cobranza SaaS por tenant: pagos, cobertura y estados."""

import uuid
from datetime import date, timedelta

import pytest

from app.services.tenant_billing_service import (
    add_months,
    billing_status,
    period_end_for,
)
from app.models.enums import TenantBillingStatus, TenantPlan


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_tenant(client, token: str) -> int:
    suffix = uuid.uuid4().hex[:8]
    response = await client.post(
        "/api/v1/admin/tenants",
        json={
            "name": f"Billing {suffix}",
            "slug": f"bill-{suffix}",
            "admin_email": f"admin-{suffix}@example.com",
            "admin_name": "Admin",
        },
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_payment(
    client, token: str, tenant_id: int, **overrides
) -> dict:
    today = date.today()
    payload = {
        "plan": "mensual",
        "amount": "150000.00",
        "period_start": (today - timedelta(days=5)).isoformat(),
        "paid_at": today.isoformat(),
        "reference": "TRX-001",
        "notes": None,
    }
    payload.update(overrides)
    response = await client.post(
        f"/api/v1/admin/tenants/{tenant_id}/payments",
        json=payload,
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_add_months_clamps_to_last_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert add_months(date(2025, 8, 15), 6) == date(2026, 2, 15)


def test_period_end_follows_plan():
    assert period_end_for(TenantPlan.mensual.value, date(2026, 3, 10)) == date(2026, 4, 10)
    assert period_end_for(TenantPlan.semestral.value, date(2026, 3, 10)) == date(2026, 9, 10)
    assert period_end_for(TenantPlan.anual.value, date(2026, 3, 10)) == date(2027, 3, 10)


def test_period_end_rejects_unknown_plan():
    with pytest.raises(ValueError):
        period_end_for("decenal", date(2026, 3, 10))


def test_billing_status_matrix():
    today = date(2026, 6, 15)
    assert (
        billing_status(None, today=today) == TenantBillingStatus.sin_registro
    )
    assert (
        billing_status(date(2026, 6, 14), today=today) == TenantBillingStatus.pendiente
    )
    assert (
        billing_status(date(2026, 6, 15), today=today) == TenantBillingStatus.por_vencer
    )
    assert (
        billing_status(date(2026, 6, 29), today=today) == TenantBillingStatus.por_vencer
    )
    assert (
        billing_status(date(2026, 6, 30), today=today) == TenantBillingStatus.al_dia
    )
    assert (
        billing_status(date(2026, 6, 1), is_internal=True, today=today)
        == TenantBillingStatus.interno
    )


@pytest.mark.asyncio
async def test_tenant_payment_is_created_with_computed_end(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    today = date.today()
    payment = await _create_payment(
        client, superuser_token, tenant_id, period_start=today.isoformat()
    )

    assert payment["plan"] == "mensual"
    assert payment["amount"] == 150000.0
    assert payment["period_end"] == add_months(today, 1).isoformat()
    assert payment["currency"] == "COP"

    listed = await client.get(
        f"/api/v1/admin/tenants/{tenant_id}/payments", headers=_auth(superuser_token)
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_list_tenants_includes_billing_status(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    today = date.today()
    await _create_payment(
        client, superuser_token, tenant_id, period_start=today.isoformat()
    )

    response = await client.get("/api/v1/admin/tenants", headers=_auth(superuser_token))
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    billing = rows[tenant_id]["billing"]

    assert billing["status"] == TenantBillingStatus.al_dia.value
    assert billing["plan"] == "mensual"
    assert billing["paid_until"] == add_months(today, 1).isoformat()
    assert billing["last_amount"] == 150000.0


@pytest.mark.asyncio
async def test_expired_coverage_marks_tenant_pending(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    today = date.today()
    await _create_payment(
        client,
        superuser_token,
        tenant_id,
        period_start=(today - timedelta(days=70)).isoformat(),
        paid_at=(today - timedelta(days=70)).isoformat(),
    )

    response = await client.get("/api/v1/admin/tenants", headers=_auth(superuser_token))
    rows = {row["id"]: row for row in response.json()}

    assert rows[tenant_id]["billing"]["status"] == TenantBillingStatus.pendiente.value


@pytest.mark.asyncio
async def test_tenant_without_payments_has_no_records(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)

    response = await client.get("/api/v1/admin/tenants", headers=_auth(superuser_token))
    rows = {row["id"]: row for row in response.json()}

    assert rows[tenant_id]["billing"]["status"] == TenantBillingStatus.sin_registro.value
    assert rows[tenant_id]["billing"]["paid_until"] is None


@pytest.mark.asyncio
async def test_default_tenant_is_internal(client, superuser_token):
    response = await client.get("/api/v1/admin/tenants", headers=_auth(superuser_token))
    rows = {row["slug"]: row for row in response.json()}

    assert rows["default"]["billing"]["status"] == TenantBillingStatus.interno.value


@pytest.mark.asyncio
async def test_payment_update_recalculates_coverage(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    today = date.today()
    payment = await _create_payment(
        client, superuser_token, tenant_id, period_start=today.isoformat()
    )

    response = await client.patch(
        f"/api/v1/admin/tenants/{tenant_id}/payments/{payment['id']}",
        json={"plan": "anual"},
        headers=_auth(superuser_token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["period_end"] == add_months(today, 12).isoformat()


@pytest.mark.asyncio
async def test_payment_delete_removes_record(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    payment = await _create_payment(client, superuser_token, tenant_id)

    response = await client.delete(
        f"/api/v1/admin/tenants/{tenant_id}/payments/{payment['id']}",
        headers=_auth(superuser_token),
    )
    assert response.status_code == 204, response.text

    listed = await client.get(
        f"/api/v1/admin/tenants/{tenant_id}/payments", headers=_auth(superuser_token)
    )
    assert listed.json() == []


@pytest.mark.asyncio
async def test_payment_amount_must_be_positive(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    response = await client.post(
        f"/api/v1/admin/tenants/{tenant_id}/payments",
        json={
            "plan": "mensual",
            "amount": "0",
            "period_start": date.today().isoformat(),
            "paid_at": date.today().isoformat(),
        },
        headers=_auth(superuser_token),
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_payment_notes_are_bounded(client, superuser_token):
    tenant_id = await _create_tenant(client, superuser_token)
    today = date.today()
    response = await client.post(
        f"/api/v1/admin/tenants/{tenant_id}/payments",
        json={
            "plan": "mensual",
            "amount": "1000",
            "period_start": today.isoformat(),
            "paid_at": today.isoformat(),
            "notes": "x" * 2001,
        },
        headers=_auth(superuser_token),
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_payment_for_unknown_tenant_returns_404(client, superuser_token):
    response = await client.get(
        "/api/v1/admin/tenants/999999/payments", headers=_auth(superuser_token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_non_superuser_cannot_manage_payments(client, student_token):
    response = await client.get(
        "/api/v1/admin/tenants/1/payments", headers=_auth(student_token)
    )
    assert response.status_code == 403

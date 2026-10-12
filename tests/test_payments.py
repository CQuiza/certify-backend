"""Pasarela de pagos: registro de estudiantes, checkout y webhook."""

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.course import CourseEnrollment
from app.models.payment import CourseOrder


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_for_sale_course(client, superuser_token, title="Curso de Pago") -> int:
    resp = await client.post(
        "/api/v1/courses",
        headers=hdr(superuser_token),
        json={
            "title": title,
            "description": "x",
            "status": "published",
            "price": 50000,
            "is_for_sale": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_register_student_and_login(client):
    payload = {
        "email": "nuevo@estudiante.example",
        "password": "StrongPass1!",
        "name": "Nuevo",
        "first_last_name": "Estudiante",
        "identity_type": "CC",
        "identity_number": "999000111",
        "phone_number": "+570000000099",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    assert "access_token" in resp.json()

    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code == 400


@pytest.mark.asyncio
async def test_checkout_requires_payments_enabled(client, superuser_token):
    course_id = await _create_for_sale_course(client, superuser_token)
    # Sin PAYMENTS_ENABLED/credenciales el checkout da 503.
    from app.api.v1.endpoints.payments import payments_configured

    if payments_configured():
        pytest.skip("pagos ya configurados en el entorno de prueba")

    # registramos un estudiante
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "comprador@example.com",
            "password": "StrongPass1!",
            "name": "Comprador",
            "first_last_name": "Uno",
            "identity_type": "CC",
            "identity_number": "999000222",
            "phone_number": "+570000000088",
        },
    )
    login = await client.post(
        "/api/v1/auth/token", data={"username": "comprador@example.com", "password": "StrongPass1!"}
    )
    token = login.json()["access_token"]

    resp = await client.post("/api/v1/payments/checkout", headers=hdr(token), json={"course_ids": [course_id]})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_checkout_and_approval_flow(client, superuser_token, monkeypatch):
    import app.api.v1.endpoints.payments as payments_mod

    course_id = await _create_for_sale_course(client, superuser_token, "Curso Checkout")
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "paga@example.com",
            "password": "StrongPass1!",
            "name": "Paga",
            "first_last_name": "Dos",
            "identity_type": "CC",
            "identity_number": "999000333",
            "phone_number": "+570000000077",
        },
    )
    login = await client.post(
        "/api/v1/auth/token", data={"username": "paga@example.com", "password": "StrongPass1!"}
    )
    token = login.json()["access_token"]

    monkeypatch.setattr(payments_mod, "payments_configured", lambda: True)

    async def fake_preference(db, order, base_url, api_prefix):
        return "https://init.mercadopago.com/fake", "PREF_123"

    monkeypatch.setattr(payments_mod, "create_preference", fake_preference)

    resp = await client.post("/api/v1/payments/checkout", headers=hdr(token), json={"course_ids": [course_id]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["init_point"] == "https://init.mercadopago.com/fake"
    order_id = body["order_id"]

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(token))
    assert order_view.status_code == 200
    assert order_view.json()["status"] == "pending"

    # RBAC: otro estudiante no puede ver el pedido
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "otro@example.com",
            "password": "StrongPass1!",
            "name": "Otro",
            "first_last_name": "Tres",
            "identity_type": "CC",
            "identity_number": "999000444",
            "phone_number": "+570000000066",
        },
    )
    other = (
        await client.post("/api/v1/auth/token", data={"username": "otro@example.com", "password": "StrongPass1!"})
    ).json()["access_token"]
    denied = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(other))
    assert denied.status_code == 403

    # Webhook aprobado (firma no obligatoria en dev; get_payment mockeado).
    async def fake_get_payment(payment_id: str):
        return {
            "id": payment_id,
            "status": "approved",
            "external_reference": order_view.json()["order_no"],
            "date_approved": "2026-10-10T12:00:00.000-04:00",
        }

    monkeypatch.setattr(payments_mod, "get_payment", fake_get_payment)
    webhook = await client.post(
        "/api/v1/payments/webhook",
        data={"type": "payment", "data.id": "PAY1"},
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["status"] == "ok"

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(token))
    assert order_view.json()["status"] == "approved"

    # Enrollado y sin duplicados tras repetir el webhook.
    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
        rows = (
            await session.execute(
                select(CourseEnrollment).where(
                    CourseEnrollment.user_id == order.user_id,
                    CourseEnrollment.course_id == course_id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1

    await client.post("/api/v1/payments/webhook", data={"type": "payment", "data.id": "PAY1"})
    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
        rows = (
            await session.execute(
                select(CourseEnrollment).where(
                    CourseEnrollment.user_id == order.user_id,
                    CourseEnrollment.course_id == course_id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1  # idempotente


@pytest.mark.asyncio
async def test_create_preference_loads_items_from_db(client, superuser_token, db, monkeypatch):
    """Regresión: create_preference debe cargar los ítems del pedido (evita MissingGreenlet)."""
    from app.models.course import Course
    from app.models.payment import CourseOrder, CourseOrderItem
    from app.services import payment_service as ps

    course = Course(title="Curso para Pref", status="published", price=40000, is_for_sale=True)
    db.add(course)
    await db.flush()
    order = CourseOrder(order_no="ORDPREF1", user_id=1, total=40000, currency="COP", status="pending")
    db.add(order)
    await db.flush()
    db.add(CourseOrderItem(order_id=order.id, course_id=course.id, unit_price=40000, course_title=course.title))
    await db.flush()

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None):
            class R:
                status_code = 200
                text = "{}"

                def json(self):
                    return {"init_point": "https://init.mp/xyz", "id": "PREF1"}

            return R()

    monkeypatch.setattr(ps.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    init_point, external_id = await ps.create_preference(db, order, "http://localhost", "/api/v1")
    assert init_point == "https://init.mp/xyz"
    assert external_id == "PREF1"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_ignored(client, monkeypatch):
    # Con secreto configurado, una firma inválida se ignora.
    from app.core import settings as settings_mod
    from app.core.settings import get_settings

    old = get_settings().mercadopago_webhook_secret
    try:
        # forzamos secreto vía objeto settings actual (cache)
        get_settings().mercadopago_webhook_secret = "secreto"
        resp = await client.post(
            "/api/v1/payments/webhook",
            data={"type": "payment", "data.id": "PAY-X"},
            headers={"x-signature": "ts=1,v1=invalid"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
    finally:
        settings_mod  # noop
        get_settings().mercadopago_webhook_secret = old
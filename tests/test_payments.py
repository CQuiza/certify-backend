"""Pasarela de pagos: registro, checkout, split, webhook resiliente y reconciliación."""

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.course import CourseEnrollment
from app.models.payment import CourseOrder
from app.services import payment_service as ps


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_for_sale_course(client, superuser_token, title="Curso de Pago") -> int:
    resp = await client.post(
        "/api/v1/courses",
        headers=hdr(superuser_token),
        json={"title": title, "description": "x", "status": "published", "price": 50000, "is_for_sale": True},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _register_student(client, email, identity, phone, name="Est", last="Prueba"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPass1!",
            "name": name,
            "first_last_name": last,
            "identity_type": "CC",
            "identity_number": identity,
            "phone_number": phone,
            "birth_date": "1990-01-01",
            "accepted_terms": True,
        },
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/token", data={"username": email, "password": "StrongPass1!"})
    assert login.status_code == 200
    return login.json()["access_token"]


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
        "birth_date": "1990-01-01",
        "accepted_terms": True,
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code >= 400


@pytest.mark.asyncio
async def test_checkout_requires_payments_enabled(client, superuser_token, student_token):
    course_id = await _create_for_sale_course(client, superuser_token)
    from app.api.v1.endpoints.payments import payments_configured

    if payments_configured():
        pytest.skip("pagos ya configurados en el entorno de prueba")
    resp = await client.post("/api/v1/payments/checkout", headers=hdr(student_token), json={"course_ids": [course_id]})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_create_preference_split_payload(db, monkeypatch):
    from app.models.course import Course
    from app.models.payment import CourseOrder, CourseOrderItem
    from app.models.platform_settings import PlatformSettings

    course = Course(title="Curso Split", status="published", price=40000, is_for_sale=True)
    db.add(course)
    await db.flush()
    order = CourseOrder(order_no="ORDERSPLIT", user_id=1, total=40000, currency="COP", status="pending")
    db.add(order)
    await db.flush()
    db.add(CourseOrderItem(order_id=order.id, course_id=course.id, unit_price=40000, course_title=course.title))
    db.add(PlatformSettings(tenant_id=order.tenant_id, mercadopago_enabled=True, mercadopago_marketplace_user_id="MP_USER_999"))
    await db.flush()

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            captured.update(json or {})
            class R:
                status_code = 200
                text = "{}"

                def json(self):
                    return {"init_point": "https://init.mp/x", "id": "PREF1"}

            return R()

    monkeypatch.setattr(ps.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    settings = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()
    settings.platform_commission_percent = 10.0
    try:
        init_point, ext = await ps.create_preference(db, order, "http://localhost", "/api/v1")
    finally:
        settings.platform_commission_percent = 0.0

    assert init_point == "https://init.mp/x"
    assert captured["marketplace"] == "MP_USER_999"
    assert captured["application_fee"] == 4000.0


@pytest.mark.asyncio
async def test_create_preference_direct_no_split(db, monkeypatch):
    """Modo directo/single: tenant habilitado sin marketplace -> sin split (todo a la cuenta del .env)."""
    from app.models.course import Course
    from app.models.payment import CourseOrder, CourseOrderItem
    from app.models.platform_settings import PlatformSettings

    course = Course(title="Curso Directo", status="published", price=30000, is_for_sale=True)
    db.add(course)
    await db.flush()
    order = CourseOrder(order_no="ORDERDIR", user_id=1, total=30000, currency="COP", status="pending")
    db.add(order)
    await db.flush()
    db.add(CourseOrderItem(order_id=order.id, course_id=course.id, unit_price=30000, course_title=course.title))
    db.add(PlatformSettings(tenant_id=order.tenant_id, mercadopago_enabled=True, mercadopago_marketplace_user_id=None))
    await db.flush()

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            captured.update(json or {})
            class R:
                status_code = 200
                text = "{}"

                def json(self):
                    return {"init_point": "https://init.mp/y", "id": "PREF2"}

            return R()

    monkeypatch.setattr(ps.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    init_point, ext = await ps.create_preference(db, order, "http://localhost", "/api/v1")
    assert init_point == "https://init.mp/y"
    assert "marketplace" not in captured
    assert "application_fee" not in captured


@pytest.mark.asyncio
async def test_checkout_disabled_tenant_503(client, superuser_token, student_token, monkeypatch):
    import app.api.v1.endpoints.payments as payments_mod

    course_id = await _create_for_sale_course(client, superuser_token, "Curso Sin Pagos")
    monkeypatch.setattr(payments_mod, "payments_configured", lambda: True)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    resp = await client.post("/api/v1/payments/checkout", headers=hdr(student_token), json={"course_ids": [course_id]})
    assert resp.status_code == 503
    assert "no está habilitado" in resp.json()["detail"]


async def _make_order(client, superuser_token, student_token, title="Curso Checkout", monkeypatch=None):
    import app.api.v1.endpoints.payments as payments_mod

    course_id = await _create_for_sale_course(client, superuser_token, title)
    if monkeypatch is not None:
        monkeypatch.setattr(payments_mod, "payments_configured", lambda: True)
        monkeypatch.setattr(ps, "payments_configured", lambda: True)

    async def fake_preference(db, order, base_url, api_prefix):
        return "https://init.mp/fake", "PREF_123"

    monkeypatch.setattr(payments_mod, "create_preference", fake_preference)
    resp = await client.post("/api/v1/payments/checkout", headers=hdr(student_token), json={"course_ids": [course_id]})
    assert resp.status_code == 200, resp.text
    return resp.json()["order_id"], course_id


@pytest.mark.asyncio
async def test_checkout_and_approval_flow_ignores_bad_signature(client, superuser_token, student_token, monkeypatch):
    order_id, course_id = await _make_order(client, superuser_token, student_token, "Curso Checkout", monkeypatch)

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(student_token))
    order_no = order_view.json()["order_no"]

    async def fake_get_payment(payment_id: str):
        return {
            "id": payment_id,
            "status": "approved",
            "external_reference": order_no,
            "date_approved": "2026-10-13T12:00:00.000-04:00",
        }

    monkeypatch.setattr(ps, "get_payment", fake_get_payment)

    # Webhook con firma inválida: no bloquea (validación server-side).
    webhook = await client.post(
        "/api/v1/payments/webhook",
        data={"type": "payment", "data.id": "PAY1"},
        headers={"x-signature": "ts=1,v1=invalid"},
    )
    assert webhook.status_code == 200
    assert webhook.json()["status"] == "ok"

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(student_token))
    assert order_view.json()["status"] == "approved"

    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
        rows = (
            await session.execute(
                select(CourseEnrollment).where(CourseEnrollment.user_id == order.user_id, CourseEnrollment.course_id == course_id)
            )
        ).scalars().all()
        assert len(rows) == 1

    # Idempotencia duplicando el webhook.
    await client.post(
        "/api/v1/payments/webhook",
        data={"type": "payment", "data.id": "PAY1"},
        headers={"x-signature": "ts=1,v1=whatever"},
    )
    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
        rows = (
            await session.execute(
                select(CourseEnrollment).where(CourseEnrollment.user_id == order.user_id, CourseEnrollment.course_id == course_id)
            )
        ).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_webhook_merchant_order_resolves_payment(client, superuser_token, student_token, monkeypatch):
    order_id, _ = await _make_order(client, superuser_token, student_token, "Curso Merchant", monkeypatch)

    async def fake_get_payment(payment_id: str):
        if payment_id == "PAY_MO":
            return {"id": "PAY_MO", "status": "approved", "external_reference": "WRONG-REF", "date_approved": None}
        raise RuntimeError("no es un payment")

    async def fake_merchant_order(merchant_id: str):
        return {"payments": [{"id": "PAY_MO"}]}

    monkeypatch.setattr(ps, "get_payment", fake_get_payment)
    monkeypatch.setattr(ps, "get_merchant_order", fake_merchant_order)

    resp = await client.post(
        "/api/v1/payments/webhook",
        json={"action": "update", "data": {"id": "MO1"}},
        params={"topic": "merchant_order"},
    )
    # Procesa sin error (external_reference ajeno -> process_payment no encuentra pedido y se ignora).
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_get_order_reconciles_pending(client, superuser_token, student_token, monkeypatch):
    order_id, course_id = await _make_order(client, superuser_token, student_token, "Curso Reconc", monkeypatch)

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(student_token))
    order_no = order_view.json()["order_no"]
    assert order_view.json()["status"] == "pending"

    async def fake_search(external_reference: str):
        return [
            {
                "id": "PAY_REC",
                "status": "approved",
                "external_reference": order_no,
                "date_approved": "2026-10-13T12:00:00.000-04:00",
            }
        ]

    monkeypatch.setattr(ps, "search_payments_by_external_reference", fake_search)

    order_view = await client.get(f"/api/v1/payments/orders/{order_id}", headers=hdr(student_token))
    assert order_view.json()["status"] == "approved"

    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(CourseOrder).where(CourseOrder.id == order_id))).scalar_one()
        rows = (
            await session.execute(
                select(CourseEnrollment).where(CourseEnrollment.user_id == order.user_id, CourseEnrollment.course_id == course_id)
            )
        ).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_payments_config_endpoints(client, superuser_token, student_token):
    headers = hdr(superuser_token)
    got = await client.get("/api/v1/configuration/payments", headers=headers)
    assert got.status_code == 200
    denied = await client.get("/api/v1/configuration/payments", headers=hdr(student_token))
    assert denied.status_code == 403
    put = await client.put(
        "/api/v1/configuration/payments",
        headers=headers,
        json={"mercadopago_enabled": True, "mercadopago_marketplace_user_id": "MP_USER_1"},
    )
    assert put.status_code == 200
    assert put.json()["mercadopago_enabled"] is True
    assert put.json()["mercadopago_marketplace_user_id"] == "MP_USER_1"


@pytest.mark.asyncio
async def test_process_payment_finds_order_across_tenants(db, tenant_b_credentials):
    """Regresión: el webhook (contexto default) debe encontrar y procesar un pedido de otro tenant."""
    from app.core.tenant import tenant_ctx
    from app.models.user import User
    from app.repositories.tenant_repository import tenant_repository

    acme = await tenant_repository.get_by_slug(db, "acme")
    assert acme is not None

    async with tenant_ctx(acme.id):
        admin = (
            await db.execute(select(User).where(User.email == "admin@acme.example"))
        ).scalar_one()
        order = CourseOrder(order_no="ORDXTEN1", user_id=admin.id, total=1000, currency="COP", status="pending")
        db.add(order)
        await db.flush()
        order_id = order.id

    # Contexto = default (como llega el webhook por el host raíz).
    payment = {
        "id": "PAYXT",
        "status": "approved",
        "external_reference": "ORDXTEN1",
        "date_approved": "2026-10-13T12:00:00-04:00",
    }
    result = await ps.process_payment(db, payment)
    assert result is not None
    assert result.status == "approved"

    async with tenant_ctx(acme.id):
        row = await db.get(CourseOrder, order_id)
        if row is not None:
            await db.delete(row)
    await db.commit()


@pytest.mark.asyncio
async def test_create_preference_back_urls_use_tenant_origin(db, monkeypatch):
    from app.models.course import Course
    from app.models.payment import CourseOrder, CourseOrderItem
    from app.models.platform_settings import PlatformSettings

    course = Course(title="Curso BackUrls", status="published", price=10000, is_for_sale=True)
    db.add(course)
    await db.flush()
    order = CourseOrder(order_no="ORDERBU", user_id=1, total=10000, currency="COP", status="pending")
    db.add(order)
    await db.flush()
    db.add(CourseOrderItem(order_id=order.id, course_id=course.id, unit_price=10000, course_title=course.title))
    db.add(PlatformSettings(tenant_id=order.tenant_id, mercadopago_enabled=True, mercadopago_marketplace_user_id=None))
    await db.flush()

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            captured.update(json or {})
            class R:
                status_code = 200
                text = "{}"

                def json(self):
                    return {"init_point": "https://init.mp/z", "id": "PREF3"}

            return R()

    monkeypatch.setattr(ps.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(ps, "payments_configured", lambda: True)

    import app.services.tenant_service as ts_mod

    async def fake_origin(db_, tenant_id):
        return "https://acme.testserver"

    monkeypatch.setattr(ts_mod.tenant_service, "origin_for_tenant_id", fake_origin)

    await ps.create_preference(db, order, "https://root.testserver", "/api/v1")
    assert captured["back_urls"]["success"].startswith("https://acme.testserver/payments/order/")
    assert captured["notification_url"].endswith("/api/v1/payments/webhook")
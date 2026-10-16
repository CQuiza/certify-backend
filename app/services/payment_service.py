"""Integración con Mercado Pago (Checkout Pro) para compra de cursos.

- Creación de preferencia (hosted) por pedido.
- Validación de la firma del webhook y consulta del estado real del pago.
- Al aprobar: inscribe al estudiante, crea el certificado "en proceso" y
  notifica por correo. Todo dentro del tenant del pedido.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.tenant import tenant_ctx, unscoped_ctx
from app.models.payment import CourseOrder

logger = logging.getLogger(__name__)

_MP_API = "https://api.mercadopago.com"


class PaymentsDisabledError(RuntimeError):
    pass


class TenantPaymentsDisabledError(RuntimeError):
    pass


def payments_configured() -> bool:
    settings = get_settings()
    return bool(settings.payments_enabled and settings.mercadopago_access_token)


def _platform_commission(order_total: float) -> float:
    """Comisión global de la plataforma (split): % + monto fijo."""
    settings = get_settings()
    percent = float(settings.platform_commission_percent or 0.0)
    fixed = float(settings.platform_commission_fixed or 0.0)
    return round(order_total * percent / 100.0, 2) + fixed


async def create_preference(db: AsyncSession, order: CourseOrder, base_url: str, api_prefix: str) -> tuple[str, str]:
    """Crea la preferencia de Checkout Pro con split de marketplace y devuelve (init_point, external_id)."""
    from sqlalchemy import select

    from app.models.payment import CourseOrderItem
    from app.models.platform_settings import PlatformSettings

    settings = get_settings()
    if not payments_configured():
        raise PaymentsDisabledError("Pagos no configurados")

    tenant_settings = (
        await db.execute(select(PlatformSettings).where(PlatformSettings.tenant_id == order.tenant_id))
    ).scalar_one_or_none()
    if tenant_settings is None or not tenant_settings.mercadopago_enabled:
        raise TenantPaymentsDisabledError(
            "El pago en línea no está habilitado para esta organización"
        )

    rows = (
        await db.execute(
            select(CourseOrderItem).where(CourseOrderItem.order_id == order.id)
        )
    ).scalars().all()

    items = []
    for item in rows:
        items.append(
            {
                "title": item.course_title,
                "quantity": 1,
                "unit_price": float(item.unit_price),
                "currency_id": settings.payments_currency,
            }
        )

    back = settings.base_url.rstrip("/")
    # Las back_urls deben volver al host del tenant (SPA con su sesión/tenant),
    # no al host raíz. La notification_url sí puede ser global (agnóstica).
    try:
        from app.services.tenant_service import tenant_service

        origin = (await tenant_service.origin_for_tenant_id(db, order.tenant_id)).rstrip("/")
    except Exception:
        logger.exception("No se pudo resolver el origen del tenant; usando BASE_URL")
        origin = back

    payload = {
        "items": items,
        "external_reference": order.order_no,
        "auto_return": "approved",
        "notification_url": f"{back}{api_prefix}/payments/webhook",
        "back_urls": {
            "success": f"{origin}/payments/order/{order.id}?status=success",
            "pending": f"{origin}/payments/order/{order.id}?status=pending",
            "failure": f"{origin}/payments/order/{order.id}?status=failure",
        },
        "statement_descriptor": settings.project_name[:22],
    }

    # Modo split (SaaS): el tenant recibe la venta y la plataforma retiene su comisión.
    # Modo directo (single / default): sin marketplace -> todo llega a la cuenta del .env.
    marketplace_id = tenant_settings.mercadopago_marketplace_user_id
    if marketplace_id:
        payload["marketplace"] = marketplace_id
        payload["application_fee"] = _platform_commission(float(order.total))
    headers = {
        "Authorization": f"Bearer {settings.mercadopago_access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{_MP_API}/checkout/preferences", json=payload, headers=headers)
    if resp.status_code >= 300:
        logger.error("MP create_preference falló — status=%s body=%s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"Error al crear el pago en Mercado Pago ({resp.status_code})")
    data = resp.json()
    init_point = data.get("init_point") or data.get("sandbox_init_point")
    if not init_point:
        raise RuntimeError("Mercado Pago no devolvió init_point")
    return str(init_point), str(data.get("id"))


async def get_payment(payment_id: str) -> dict:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.mercadopago_access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{_MP_API}/v1/payments/{payment_id}", headers=headers)
    if resp.status_code >= 300:
        logger.error("MP get_payment falló — status=%s", resp.status_code)
        raise RuntimeError("Error consultando el pago en Mercado Pago")
    return resp.json()


async def get_merchant_order(merchant_order_id: str) -> dict:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.mercadopago_access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{_MP_API}/v1/merchant_orders/{merchant_order_id}", headers=headers
        )
    if resp.status_code >= 300:
        logger.error("MP get_merchant_order falló — status=%s", resp.status_code)
        raise RuntimeError("Error consultando la orden de Mercado Pago")
    return resp.json()


async def resolve_payment_from_notification(
    data_id: str, topic: str | None = None, action: str | None = None
) -> dict | None:
    """Resuelve el payment id real a partir de la notificación.

    - Eventos `payment`/`payment.created` → data.id es el payment.
    - Eventos de `merchant_order` → data.id es una merchant_order; se deriva el
      primer payment de su lista.
    """
    is_merchant = bool(
        (topic and "merchant_order" in topic.lower())
        or (action and "merchant_order" in action.lower())
    )
    if is_merchant:
        merchant_order = await get_merchant_order(data_id)
        payments = merchant_order.get("payments") or []
        real = next((p.get("id") for p in payments if p.get("id")), None)
        if real:
            return await get_payment(str(real))
        return None

    try:
        return await get_payment(data_id)
    except RuntimeError:
        # Puede ser una merchant_order aunque el tema no lo indique.
        try:
            merchant_order = await get_merchant_order(data_id)
        except RuntimeError:
            return None
        payments = merchant_order.get("payments") or []
        real = next((p.get("id") for p in payments if p.get("id")), None)
        if real:
            return await get_payment(str(real))
        return None


async def search_payments_by_external_reference(external_reference: str) -> list[dict]:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.mercadopago_access_token}"}
    params = {"external_reference": external_reference}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{_MP_API}/v1/payments/search", params=params, headers=headers
        )
    if resp.status_code >= 300:
        logger.error("MP payments/search falló — status=%s", resp.status_code)
        raise RuntimeError("Error buscando el pago en Mercado Pago")
    return resp.json().get("results") or []


async def reconcile_order(db: AsyncSession, order: CourseOrder) -> CourseOrder:
    """Si el pedido está pending, busca el pago por external_reference y procesa (directo sin webhook)."""
    if order.status != "pending":
        return order
    if not payments_configured():
        return order
    try:
        payments = await search_payments_by_external_reference(order.order_no)
    except RuntimeError:
        return order
    for payment in payments:
        if str(payment.get("status") or "").lower() == "approved":
            processed = await process_payment(db, payment)
            if processed is not None:
                order = processed
            break
    return order


def verify_webhook_signature(request) -> bool:
    """Verifica x-signature (MP v2: ts, v1). Devuelve True si no hay secreto (modo dev)."""
    settings = get_settings()
    secret = settings.mercadopago_webhook_secret
    if not secret:
        return True

    x_signature = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    data_id = request.query_params.get("data.id") or request.query_params.get("id")

    params: dict[str, str] = {}
    for part in x_signature.replace(" ", "").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v

    ts = params.get("ts")
    v1 = params.get("v1")
    if not (ts and v1 and data_id):
        return False

    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    digest = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, v1)


async def process_payment(db: AsyncSession, payment: dict) -> CourseOrder | None:
    """Marca el pedido según el estado real y materializa la compra si fue aprobado."""
    external_reference = str(payment.get("external_reference") or "")
    status = str(payment.get("status") or "").lower()
    if not external_reference:
        return None

    from sqlalchemy import select

    from app.models.course import Course
    from app.models.payment import CourseOrderItem
    from app.models.user import User
    from app.repositories.enrollment_repository import course_enrollment_repository
    from app.repositories.pending_certificate_repository import pending_certificate_repository

    # El webhook es público (llega por el host de la plataforma), así que el
    # pedido se busca SIN scope de tenant (order_no es único global); luego se
    # procesa dentro del tenant del propio pedido.
    async with unscoped_ctx():
        result = await db.execute(
            select(CourseOrder).where(CourseOrder.order_no == external_reference)
        )
        order = result.scalar_one_or_none()
    if order is None:
        logger.warning("Webhook: pedido %s no encontrado", external_reference)
        return None

    if order.status == "approved" and status == "approved":
        return order  # ya procesado (idempotente)

    async with tenant_ctx(order.tenant_id):
        if status == "approved":
            order.status = "approved"
            order.external_id = str(payment.get("id"))
            order.paid_at = (
                __import__("datetime").datetime.fromisoformat(payment["date_approved"].replace("Z", "+00:00"))
                if payment.get("date_approved")
                else None
            )

            items = (
                await db.execute(
                    select(CourseOrderItem).where(CourseOrderItem.order_id == order.id)
                )
            ).scalars().all()

            if order.kind == "renewal" and order.renewal_certificate_id:
                from app.models.certificate import Certificate
                from app.services.certificate_lifecycle import reset_course_progress

                cert = (
                    await db.execute(
                        select(Certificate).where(Certificate.id == order.renewal_certificate_id)
                    )
                ).scalar_one_or_none()
                for item in items:
                    course = (
                        await db.execute(select(Course).where(Course.id == item.course_id))
                    ).scalar_one_or_none()
                    if course is None:
                        continue
                    existing = await course_enrollment_repository.get_by_user_course(
                        db, order.user_id, course.id
                    )
                    if existing is None:
                        await course_enrollment_repository.create(
                            db, user_id=order.user_id, course_id=course.id
                        )
                    # Reiniciar progreso: debe volver a superar el curso.
                    await reset_course_progress(db, user_id=order.user_id, course_id=course.id)
                    # Solicitud de renovación (al 100% renueva el mismo certificado).
                    pc = await pending_certificate_repository.get_by_user_and_course(
                        db, order.user_id, course.id
                    )
                    renewal_fields = {
                        "status": "in_progress",
                        "renewal_of_certificate_id": cert.id if cert else None,
                        "certificate_type_id": cert.certificate_type_id if cert else course.certificate_type_id,
                        "created_by": order.user_id,
                        "issued_certificate_id": None,
                        "issued_at": None,
                    }
                    if pc is None:
                        pc = await pending_certificate_repository.create(
                            db,
                            user_id=order.user_id,
                            course_id=course.id,
                            certificate_type_id=cert.certificate_type_id if cert else course.certificate_type_id,
                            created_by=order.user_id,
                        )
                    await pending_certificate_repository.update(db, pc, renewal_fields)
            else:
                for item in items:
                    course = (
                        await db.execute(select(Course).where(Course.id == item.course_id))
                    ).scalar_one_or_none()
                    if course is None:
                        continue
                    existing = await course_enrollment_repository.get_by_user_course(
                        db, order.user_id, course.id
                    )
                    if existing is None:
                        await course_enrollment_repository.create(
                            db, user_id=order.user_id, course_id=course.id
                        )
                    if course.certificate_type_id:
                        pc = await pending_certificate_repository.get_by_user_and_course(
                            db, order.user_id, course.id
                        )
                        if pc is None:
                            await pending_certificate_repository.create(
                                db,
                                user_id=order.user_id,
                                course_id=course.id,
                                certificate_type_id=course.certificate_type_id,
                                created_by=order.user_id,
                            )

            user = (
                await db.execute(select(User).where(User.id == order.user_id))
            ).scalar_one_or_none()
            if user:
                from app.utils.email import send_purchase_confirmation_email

                titles = [i.course_title for i in items]
                await send_purchase_confirmation_email(
                    user.email,
                    user.name,
                    titles,
                    float(order.total),
                    tenant_id=order.tenant_id,
                )
            logger.info("Pedido aprobado — order=%s", order.order_no)
        elif status in ("cancelled", "rejected"):
            order.status = "cancelled" if status == "cancelled" else "failed"
            logger.info("Pedido %s — %s", order.order_no, order.status)
        else:
            order.status = "pending"
            order.external_id = str(payment.get("id"))
        await db.flush()
        await db.refresh(order)
        return order
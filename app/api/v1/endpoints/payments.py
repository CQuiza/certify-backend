"""Pagos de cursos con Mercado Pago (Checkout Pro)."""

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.course import Course
from app.models.enums import CourseStatus
from app.models.payment import CourseOrder, CourseOrderItem
from app.models.user import User
from app.schemas.payment import CheckoutRequest, CheckoutResponse, OrderItemRead, OrderRead
from app.services.access import is_super_or_admin
from app.services.payment_service import (
    PaymentsDisabledError,
    TenantPaymentsDisabledError,
    create_preference,
    get_payment,
    payments_configured,
    process_payment,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


def _new_order_no() -> str:
    return f"ORD{int(time.time())}{uuid.uuid4().hex[:6].upper()}"


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    body: CheckoutRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    if current.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Solo estudiantes pueden comprar cursos"
        )
    if not payments_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El pago en línea no está disponible en este momento",
        )

    ids = list(dict.fromkeys(body.course_ids))
    rows = (
        await db.execute(select(Course).where(Course.id.in_(ids)))
    ).scalars().all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Algún curso no existe")

    for course in rows:
        if course.status != CourseStatus.published.value or not course.is_for_sale or not course.price or course.price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El curso '{course.title}' no está disponible para compra",
            )

    settings = get_settings()
    total = sum(course.price for course in rows)  # type: ignore[operator]
    order = CourseOrder(
        order_no=_new_order_no(),
        user_id=current.id,
        total=total,
        currency=settings.payments_currency,
        status="pending",
    )
    db.add(order)
    await db.flush()
    for course in rows:
        db.add(
            CourseOrderItem(
                order_id=order.id,
                course_id=course.id,
                unit_price=course.price,
                course_title=course.title,
            )
        )
    await db.flush()

    base = settings.base_url.rstrip("/")
    try:
        init_point, external_id = await create_preference(
            db, order, base, settings.api_v1_prefix
        )
    except TenantPaymentsDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except PaymentsDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    order.external_id = external_id
    await db.commit()
    logger.info("Checkout creado — order=%s user=%s total=%s", order.order_no, current.id, total)
    return CheckoutResponse(order_id=order.id, init_point=init_point)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    order = (
        await db.execute(select(CourseOrder).where(CourseOrder.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    if order.user_id != current.id and not is_super_or_admin(current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso")

    items = (
        await db.execute(select(CourseOrderItem).where(CourseOrderItem.order_id == order.id))
    ).scalars().all()
    return OrderRead(
        id=order.id,
        order_no=order.order_no,
        total=order.total,
        currency=order.currency,
        status=order.status,
        created_at=order.created_at,
        paid_at=order.paid_at,
        items=[OrderItemRead.model_validate(i) for i in items],
    )


@router.post("/webhook")
async def payment_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Notificación de Mercado Pago. Pública; se verifica la firma y el estado real."""
    try:
        raw = await request.body()
        import json

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            form = await request.form()
            data = dict(form)
        payment_id = None
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                payment_id = inner.get("id")
            if payment_id is None:
                payment_id = data.get("data.id") or data.get("id")
    except Exception:
        logger.exception("Webhook: error parseando notificación")
        return {"status": "ignored"}

    if not payment_id:
        return {"status": "ignored"}

    if not verify_webhook_signature(request):
        logger.warning("Webhook: firma inválida para payment=%s", payment_id)
        return {"status": "ignored"}

    try:
        payment = await get_payment(str(payment_id))
        await process_payment(db, payment)
        await db.commit()
    except Exception:
        logger.exception("Webhook: error procesando payment=%s", payment_id)
        return {"status": "error"}
    return {"status": "ok"}
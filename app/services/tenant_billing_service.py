"""Cobranza SaaS por tenant: pagos, cobertura y estado de vigencia.

Cada registro es un pago recibido que cubre un período. El estado se deriva
siempre al leer; no hay jobs, correos ni suspensiones automáticas.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TenantBillingStatus, TenantPlan
from app.models.tenant_payment import TenantPayment
from app.schemas.tenant_payment import (
    TenantBilling,
    TenantPaymentCreate,
    TenantPaymentUpdate,
)

# Días de aviso antes del vencimiento para "por vencer".
WARN_DAYS = 15

# El tenant de plataforma no se cobra ni alerta.
INTERNAL_TENANT_SLUG = "default"

PLAN_MONTHS: dict[str, int] = {
    TenantPlan.mensual.value: 1,
    TenantPlan.semestral.value: 6,
    TenantPlan.anual.value: 12,
}


def add_months(start: date, months: int) -> date:
    """Suma meses de calendario con clamp al último día del mes destino."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def period_end_for(plan: str, period_start: date) -> date:
    """Calcula el fin de cobertura (inclusive) según el plan contratado."""
    months = PLAN_MONTHS.get(plan)
    if months is None:
        raise ValueError(f"Plan no válido: {plan}")
    return add_months(period_start, months)


def billing_status(
    paid_until: date | None,
    *,
    is_internal: bool = False,
    today: date | None = None,
) -> TenantBillingStatus:
    """Estado derivado; `paid_until` es el último día cubierto (inclusive)."""
    if is_internal:
        return TenantBillingStatus.interno
    if paid_until is None:
        return TenantBillingStatus.sin_registro
    reference = today or date.today()
    if paid_until < reference:
        return TenantBillingStatus.pendiente
    if paid_until < reference + timedelta(days=WARN_DAYS):
        return TenantBillingStatus.por_vencer
    return TenantBillingStatus.al_dia


class TenantBillingService:
    async def list_payments(
        self, db: AsyncSession, tenant_id: int
    ) -> list[TenantPayment]:
        result = await db.execute(
            select(TenantPayment)
            .where(TenantPayment.tenant_id == tenant_id)
            .order_by(TenantPayment.period_end.desc(), TenantPayment.id.desc())
        )
        return list(result.scalars().all())

    async def get_payment(
        self, db: AsyncSession, tenant_id: int, payment_id: int
    ) -> TenantPayment | None:
        result = await db.execute(
            select(TenantPayment).where(
                TenantPayment.id == payment_id,
                TenantPayment.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_payment(
        self,
        db: AsyncSession,
        *,
        tenant_id: int,
        data: TenantPaymentCreate,
        created_by: int | None,
    ) -> TenantPayment:
        row = TenantPayment(
            tenant_id=tenant_id,
            plan=data.plan.value,
            amount=data.amount,
            currency=data.currency.upper(),
            period_start=data.period_start,
            period_end=period_end_for(data.plan.value, data.period_start),
            paid_at=data.paid_at,
            reference=data.reference,
            notes=data.notes,
            created_by=created_by,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def update_payment(
        self,
        db: AsyncSession,
        payment: TenantPayment,
        data: TenantPaymentUpdate,
    ) -> TenantPayment:
        fields = data.model_dump(exclude_unset=True)
        if "plan" in fields and fields["plan"] is not None:
            fields["plan"] = fields["plan"].value
        if "currency" in fields and fields["currency"] is not None:
            fields["currency"] = fields["currency"].upper()

        recalculate = False
        nullable_fields = {"reference", "notes"}
        for key, value in fields.items():
            if value is None and key not in nullable_fields:
                continue
            if key in ("plan", "period_start"):
                recalculate = True
            setattr(payment, key, value)
        if recalculate:
            payment.period_end = period_end_for(payment.plan, payment.period_start)

        await db.flush()
        await db.refresh(payment)
        return payment

    async def delete_payment(self, db: AsyncSession, payment: TenantPayment) -> None:
        await db.delete(payment)
        await db.flush()

    async def summaries(
        self,
        db: AsyncSession,
        tenants: Iterable[tuple[int, str]],
    ) -> dict[int, TenantBilling]:
        """Estado de cobranza de varios tenants con una sola consulta."""
        tenant_rows = list(tenants)
        if not tenant_rows:
            return {}
        tenant_ids = [tenant_id for tenant_id, _ in tenant_rows]

        result = await db.execute(
            select(TenantPayment)
            .where(TenantPayment.tenant_id.in_(tenant_ids))
            .order_by(TenantPayment.tenant_id, TenantPayment.period_end.desc())
        )
        latest: dict[int, TenantPayment] = {}
        for payment in result.scalars().all():
            latest.setdefault(payment.tenant_id, payment)

        today = date.today()
        summaries: dict[int, TenantBilling] = {}
        for tenant_id, slug in tenant_rows:
            last = latest.get(tenant_id)
            paid_until = last.period_end if last else None
            summaries[tenant_id] = TenantBilling(
                status=billing_status(
                    paid_until,
                    is_internal=slug == INTERNAL_TENANT_SLUG,
                    today=today,
                ),
                paid_until=paid_until,
                plan=last.plan if last else None,
                last_amount=float(last.amount) if last else None,
            )
        return summaries


tenant_billing_service = TenantBillingService()

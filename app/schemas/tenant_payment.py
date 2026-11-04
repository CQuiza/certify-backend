"""Esquemas de cobranza SaaS por tenant."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TenantBillingStatus, TenantPlan


class TenantPaymentCreate(BaseModel):
    plan: TenantPlan
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="COP", max_length=10)
    period_start: date
    paid_at: date
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class TenantPaymentUpdate(BaseModel):
    plan: TenantPlan | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, max_length=10)
    period_start: date | None = None
    paid_at: date | None = None
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class TenantPaymentRead(BaseModel):
    id: int
    tenant_id: int
    plan: str
    amount: float
    currency: str
    period_start: date
    period_end: date
    paid_at: date
    reference: str | None
    notes: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TenantBilling(BaseModel):
    """Estado de cobranza derivado de la cobertura pagada."""

    status: TenantBillingStatus
    paid_until: date | None = None
    plan: str | None = None
    last_amount: float | None = None

"""Esquemas de pagos / órdenes de compra."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CheckoutRequest(BaseModel):
    course_ids: list[int] = Field(..., min_length=1, max_length=50)


class CheckoutResponse(BaseModel):
    order_id: int | None = None
    init_point: str | None = None
    free: bool = False
    detail: str | None = None


class OrderItemRead(BaseModel):
    course_id: int
    course_title: str
    unit_price: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: int
    order_no: str
    total: Decimal
    currency: str
    status: str
    created_at: datetime | None = None
    paid_at: datetime | None = None
    items: list[OrderItemRead] = []

    model_config = ConfigDict(from_attributes=True)
"""Eventos de webhook de pago procesados (idempotencia)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    order_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("course_orders.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str | None] = mapped_column(String(30))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

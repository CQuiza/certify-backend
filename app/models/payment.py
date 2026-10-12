"""Pedidos y ítems de compra de cursos (pasarela Mercado Pago)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import TenantScoped

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User

ORDER_STATUSES = ("pending", "approved", "failed", "cancelled")


class CourseOrder(TenantScoped, Base):
    __tablename__ = "course_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_course_orders_order_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="COP")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    external_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User")
    items: Mapped[list[CourseOrderItem]] = relationship(
        "CourseOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class CourseOrderItem(TenantScoped, Base):
    __tablename__ = "course_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "course_id", name="uq_course_order_items_order_course"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_orders.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    course_title: Mapped[str] = mapped_column(String(255), nullable=False)

    order: Mapped[CourseOrder] = relationship("CourseOrder", back_populates="items")
    course: Mapped[Course] = relationship("Course")
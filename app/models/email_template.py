"""Plantillas de correo personalizables por tipo."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.platform_settings import PlatformSettings
    from app.models.user import User

_EMAIL_TEMPLATE_KINDS = ("credentials", "certificate_issued", "certificate_expired")


class EmailTemplate(Base):
    """Asunto y cuerpo HTML de un correo, personalizables por superuser."""

    __tablename__ = "email_templates"
    __table_args__ = (
        UniqueConstraint(
            "platform_settings_id", "kind", name="uq_email_template_settings_kind"
        ),
        CheckConstraint(
            "kind IN ('credentials', 'certificate_issued', 'certificate_expired')",
            name="kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_settings_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("platform_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )

    platform_settings: Mapped[PlatformSettings] = relationship(
        "PlatformSettings", back_populates="templates"
    )
    updater: Mapped[User | None] = relationship("User", foreign_keys=[updated_by])

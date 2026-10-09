"""Configuración personalizable de la plataforma (una fila por tenant)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
    from app.models.email_template import EmailTemplate
    from app.models.tenant import Tenant
    from app.models.user import User

#: Mensaje del dashboard. Los placeholders se interpolan con
#: ``app_name`` y ``organization`` al renderizar.
DEFAULT_DASHBOARD_MESSAGE = (
    "Panel principal de la plataforma {{app_name}} para la organización {{organization}}"
)


class PlatformSettings(Base):
    """Personalización de organización, marca y mensajería (una fila por tenant)."""

    __tablename__ = "platform_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_platform_settings_tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # ── Organización / marca ──────────────────────────────────
    organization_name: Mapped[str | None] = mapped_column(String(255))
    dashboard_message: Mapped[str | None] = mapped_column(Text)
    branding_logo_object_key: Mapped[str | None] = mapped_column(String(255))

    # ── Correo saliente (SMTP) ────────────────────────────────
    smtp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int | None] = mapped_column(Integer)
    smtp_user: Mapped[str | None] = mapped_column(String(255))
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text)
    smtp_tls: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_from: Mapped[str | None] = mapped_column(String(255))
    email_from_name: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )

    templates: Mapped[list[EmailTemplate]] = relationship(
        "EmailTemplate",
        back_populates="platform_settings",
        cascade="all, delete-orphan",
    )
    updater: Mapped[User | None] = relationship("User", foreign_keys=[updated_by])
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="settings")

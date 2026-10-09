"""Solicitud de certificado en proceso (emitido al completar el curso)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import TenantScoped

if TYPE_CHECKING:
    from app.models.certificate import Certificate
    from app.models.certificate_type import CertificateType
    from app.models.course import Course
    from app.models.user import User


class PendingCertificate(TenantScoped, Base):
    """Certificado retenido: se emite automáticamente cuando el estudiante
    completa el curso al 100%."""

    __tablename__ = "pending_certificates"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_pending_user_course"),
        CheckConstraint(
            "status IN ('in_progress', 'issued')",
            name="status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    certificate_type_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("certificate_types.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress", server_default="in_progress"
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_at_override: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validity_extension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_certificate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("certificates.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course | None] = relationship("Course", foreign_keys=[course_id])
    certificate_type: Mapped[CertificateType | None] = relationship(
        "CertificateType", foreign_keys=[certificate_type_id]
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    issued_certificate: Mapped[Certificate | None] = relationship(
        "Certificate", foreign_keys=[issued_certificate_id]
    )
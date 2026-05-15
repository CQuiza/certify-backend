"""Modelos ORM — importar para registrar metadatos."""

from app.core.database import Base
from app.models.certificate import Certificate
from app.models.certificate_audit import CertificateAudit
from app.models.certificate_type import CertificateType
from app.models.course import Course, CourseEnrollment
from app.models.enums import (
    CertificateAuditAction,
    CertificateStatus,
    CertificateTypeKind,
    CourseStatus,
    IdentityType,
    UserRole,
    ValidityUnit,
)
from app.models.lesson import Lesson
from app.models.module import Module
from app.models.progress import UserProgress
from app.models.user import User

__all__ = [
    "Base",
    "Certificate",
    "CertificateAudit",
    "CertificateType",
    "CertificateAuditAction",
    "CertificateStatus",
    "CertificateTypeKind",
    "Course",
    "CourseEnrollment",
    "CourseStatus",
    "IdentityType",
    "Lesson",
    "Module",
    "User",
    "UserProgress",
    "UserRole",
    "ValidityUnit",
]

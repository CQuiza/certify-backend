"""Agregador de rutas /api/v1."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    certificate_audit,
    certificate_types,
    certificates,
    course_enrollments,
    courses,
    health,
    lessons,
    modules,
    user_progress,
    users,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(courses.router)
api_router.include_router(modules.router)
api_router.include_router(lessons.router)
api_router.include_router(user_progress.router)
api_router.include_router(certificate_types.router)
api_router.include_router(certificates.router)
api_router.include_router(certificate_audit.router)
api_router.include_router(course_enrollments.router)

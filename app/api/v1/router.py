"""Routers de /api/v1.

Se exponen como lista plana: cada router se incluye directo sobre la app con
el prefijo de versión (evita ramas anidadas de `_IncludedRouter` que en
FastAPI>=0.142 pierden rutas).
"""

from app.api.v1.endpoints import (
    admin_tenants,
    auth,
    certificate_audit,
    certificate_types,
    certificates,
    configuration,
    course_enrollments,
    courses,
    dashboard,
    email_audit,
    health,
    lesson_files,
    lessons,
    module_assessments,
    modules,
    monitoring,
    reports,
    tasks,
    task_submissions,
    user_audit,
    user_progress,
    users,
    worker_audit,
)

ROUTERS = [
    health.router,
    admin_tenants.router,
    auth.router,
    users.router,
    courses.router,
    modules.router,
    module_assessments.router,
    lessons.router,
    lesson_files.router,
    user_progress.router,
    certificate_types.router,
    certificates.router,
    certificate_audit.router,
    dashboard.router,
    configuration.router,
    monitoring.router,
    reports.router,
    course_enrollments.router,
    email_audit.router,
    tasks.router,
    task_submissions.router,
    user_audit.router,
    worker_audit.router,
]

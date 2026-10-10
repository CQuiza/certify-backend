"""Generadores de reportes analíticos (por tenant).

Cada reporte devuelve ``(columns, rows)`` donde ``columns`` describe el
encabezado y ``rows`` es una lista de dicts. El rango de fechas se aplica a una
columna "ancla" propia de cada reporte.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Callable

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.certificate import Certificate
from app.models.certificate_audit import CertificateAudit
from app.models.certificate_type import CertificateType
from app.models.course import Course, CourseEnrollment
from app.models.lesson import Lesson
from app.models.lesson_task import LessonTask
from app.models.module import Module
from app.models.module_assessment import ModuleAssessment
from app.models.task_submission import TaskSubmission
from app.models.user import User
from app.models.user_assessment_attempt import UserAssessmentAttempt

Column = dict[str, str]
ReportFn = Callable[[AsyncSession, datetime | None, datetime | None, int], Any]


def parse_range(start_date: str | None, end_date: str | None) -> tuple[datetime | None, datetime | None]:
    start = None
    end = None
    if start_date:
        start = datetime.combine(date.fromisoformat(start_date), time.min, tzinfo=UTC)
    if end_date:
        end = datetime.combine(date.fromisoformat(end_date), time.max, tzinfo=UTC)
    return start, end


def _full_name(user: User | None) -> str:
    if user is None:
        return "—"
    parts = [user.name, user.first_last_name, user.second_last_name]
    return " ".join(p for p in parts if p) or user.email


# ── Reportes ────────────────────────────────────────────────


async def _certificates_by_admin(db, start, end, limit) -> list[dict]:
    performer = aliased(User)
    student = aliased(User)
    stmt = (
        select(
            CertificateAudit.timestamp,
            Certificate.unique_id,
            Certificate.status,
            CertificateType.type,
            CertificateType.name,
            performer.id,
            performer.name,
            performer.first_last_name,
            performer.email,
            student.name,
            student.first_last_name,
            student.identity_number,
            student.email,
        )
        .select_from(CertificateAudit)
        .join(Certificate, CertificateAudit.certificate_id == Certificate.id)
        .outerjoin(CertificateType, Certificate.certificate_type_id == CertificateType.id)
        .outerjoin(performer, CertificateAudit.performed_by == performer.id)
        .outerjoin(student, Certificate.user_id == student.id)
        .where(CertificateAudit.action == "issued")
    )
    if start is not None:
        stmt = stmt.where(CertificateAudit.timestamp >= start)
    if end is not None:
        stmt = stmt.where(CertificateAudit.timestamp <= end)
    stmt = stmt.order_by(CertificateAudit.timestamp.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    out = []
    for r in rows:
        admin_name = " ".join(p for p in (r[6], r[7]) if p) or (r[8] or "—")
        student_name = " ".join(p for p in (r[9], r[10]) if p) or (r[12] or "—")
        out.append(
            {
                "fecha": r[0].isoformat() if r[0] else None,
                "admin_id": r[5],
                "admin": admin_name,
                "admin_email": r[8],
                "tipo": r[3],
                "tipo_nombre": r[4],
                "estudiante": student_name,
                "estudiante_identidad": r[11],
                "estudiante_email": r[12],
                "uuid": str(r[1]) if r[1] else None,
                "estado": r[2],
            }
        )
    return out


async def _certificates_by_type(db, start, end, limit) -> list[dict]:
    stmt = (
        select(
            CertificateType.type,
            CertificateType.name,
            Certificate.status,
            func.count(Certificate.id),
        )
        .join(Certificate, Certificate.certificate_type_id == CertificateType.id)
        .group_by(CertificateType.type, CertificateType.name, Certificate.status)
    )
    if start is not None:
        stmt = stmt.where(Certificate.issued_at >= start)
    if end is not None:
        stmt = stmt.where(Certificate.issued_at <= end)
    rows = (await db.execute(stmt)).all()

    agg: dict[tuple, dict] = {}
    for tipo, nombre, status, count in rows:
        key = (tipo, nombre)
        entry = agg.setdefault(
            key,
            {"tipo": tipo, "tipo_nombre": nombre, "total": 0, "activos": 0, "revocados": 0, "expirados": 0},
        )
        entry["total"] += count
        if status == "active":
            entry["activos"] += count
        elif status == "revoked":
            entry["revocados"] += count
        elif status == "expired":
            entry["expirados"] += count
    return sorted(agg.values(), key=lambda x: x["total"], reverse=True)


async def _content_by_teacher(db, start, end, limit) -> list[dict]:
    teacher = aliased(User)
    stmt = (
        select(
            teacher.id,
            teacher.name,
            teacher.first_last_name,
            teacher.email,
            func.count(func.distinct(Course.id)),
            func.count(func.distinct(Module.id)),
            func.count(func.distinct(Lesson.id)),
            func.count(func.distinct(ModuleAssessment.id)),
            func.count(func.distinct(LessonTask.id)),
        )
        .select_from(teacher)
        .join(Course, Course.teacher_id == teacher.id)
        .outerjoin(Module, Module.course_id == Course.id)
        .outerjoin(Lesson, Lesson.module_id == Module.id)
        .outerjoin(ModuleAssessment, ModuleAssessment.module_id == Module.id)
        .outerjoin(LessonTask, LessonTask.lesson_id == Lesson.id)
        .where(teacher.role == "teacher")
    )
    if start is not None:
        stmt = stmt.where(Course.created_at >= start)
    if end is not None:
        stmt = stmt.where(Course.created_at <= end)
    stmt = stmt.group_by(teacher.id, teacher.name, teacher.first_last_name, teacher.email)
    rows = (await db.execute(stmt)).all()
    out = []
    for r in rows:
        name = " ".join(p for p in (r[1], r[2]) if p) or (r[3] or "—")
        out.append(
            {
                "docente_id": r[0],
                "docente": name,
                "email": r[3],
                "cursos": r[4],
                "modulos": r[5],
                "lecciones": r[6],
                "evaluaciones": r[7],
                "tareas": r[8],
            }
        )
    return sorted(out, key=lambda x: x["cursos"], reverse=True)


async def _courses_assigned_by_user(db, start, end, limit) -> list[dict]:
    stmt = (
        select(
            User.id,
            User.name,
            User.first_last_name,
            User.email,
            Course.title,
            CourseEnrollment.enrolled_at,
        )
        .select_from(CourseEnrollment)
        .join(User, CourseEnrollment.user_id == User.id)
        .join(Course, CourseEnrollment.course_id == Course.id)
    )
    if start is not None:
        stmt = stmt.where(CourseEnrollment.enrolled_at >= start)
    if end is not None:
        stmt = stmt.where(CourseEnrollment.enrolled_at <= end)
    stmt = stmt.order_by(CourseEnrollment.enrolled_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()

    agg: dict[int, dict] = {}
    for uid, name, fl, email, ctitle, enrolled in rows:
        entry = agg.setdefault(
            uid,
            {
                "estudiante_id": uid,
                "estudiante": " ".join(p for p in (name, fl) if p) or email,
                "email": email,
                "total_cursos": 0,
                "cursos": [],
            },
        )
        entry["total_cursos"] += 1
        entry["cursos"].append(ctitle)
    result = list(agg.values())
    for e in result:
        e["cursos"] = ", ".join(e["cursos"])
    return sorted(result, key=lambda x: x["total_cursos"], reverse=True)


async def _users_by_role(db, start, end, limit) -> list[dict]:
    stmt = select(User.role, func.count(User.id)).group_by(User.role)
    if start is not None:
        stmt = stmt.where(User.created_at >= start)
    if end is not None:
        stmt = stmt.where(User.created_at <= end)
    rows = (await db.execute(stmt)).all()
    return [{"rol": r[0], "cantidad": r[1]} for r in rows]


async def _assessment_results(db, start, end, limit) -> list[dict]:
    stmt = (
        select(
            Course.title,
            Module.title,
            ModuleAssessment.id,
            ModuleAssessment.passing_score,
            func.count(UserAssessmentAttempt.id),
            func.avg(UserAssessmentAttempt.score),
            func.sum(func.cast(UserAssessmentAttempt.passed, Integer)),
        )
        .select_from(ModuleAssessment)
        .join(Module, ModuleAssessment.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .outerjoin(UserAssessmentAttempt, UserAssessmentAttempt.assessment_id == ModuleAssessment.id)
        .group_by(Course.title, Module.title, ModuleAssessment.id, ModuleAssessment.passing_score)
    )
    if start is not None:
        stmt = stmt.where((UserAssessmentAttempt.finished_at >= start) | (UserAssessmentAttempt.id.is_(None)))
    if end is not None:
        stmt = stmt.where((UserAssessmentAttempt.finished_at <= end) | (UserAssessmentAttempt.id.is_(None)))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    out = []
    for curso, modulo, aid, passing, intentos, avg, passed in rows:
        intentos = intentos or 0
        aprobados = int(passed or 0)
        out.append(
            {
                "curso": curso,
                "modulo": modulo,
                "evaluacion_id": aid,
                "nota_minima": passing,
                "intentos": intentos,
                "promedio": round(float(avg), 2) if avg is not None else None,
                "aprobados": aprobados,
                "porcentaje_aprobacion": round((aprobados / intentos) * 100, 2) if intentos else 0,
            }
        )
    return out


async def _certificates_status_flow(db, start, end, limit) -> list[dict]:
    stmt = select(CertificateAudit.action, func.count(CertificateAudit.id)).group_by(CertificateAudit.action)
    if start is not None:
        stmt = stmt.where(CertificateAudit.timestamp >= start)
    if end is not None:
        stmt = stmt.where(CertificateAudit.timestamp <= end)
    rows = (await db.execute(stmt)).all()
    return [{"accion": r[0], "cantidad": r[1]} for r in rows]


async def _top_courses(db, start, end, limit) -> list[dict]:
    stmt = (
        select(Course.id, Course.title, func.count(CourseEnrollment.id))
        .select_from(CourseEnrollment)
        .join(Course, CourseEnrollment.course_id == Course.id)
        .group_by(Course.id, Course.title)
    )
    if start is not None:
        stmt = stmt.where(CourseEnrollment.enrolled_at >= start)
    if end is not None:
        stmt = stmt.where(CourseEnrollment.enrolled_at <= end)
    stmt = stmt.order_by(func.count(CourseEnrollment.id).desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [{"curso_id": r[0], "curso": r[1], "inscritos": r[2]} for r in rows]


async def _activity_monthly(db, start, end, limit) -> list[dict]:
    async def _dates(stmt, col):
        if start is not None:
            stmt = stmt.where(col >= start)
        if end is not None:
            stmt = stmt.where(col <= end)
        return [d for (d,) in (await db.execute(stmt)).all() if d is not None]

    cert_dates = await _dates(select(Certificate.issued_at), Certificate.issued_at)
    enr_dates = await _dates(select(CourseEnrollment.enrolled_at), CourseEnrollment.enrolled_at)
    user_dates = await _dates(select(User.created_at), User.created_at)

    buckets: dict[str, dict] = {}

    def bump(dt, field):
        if dt is None:
            return
        key = dt.strftime("%Y-%m")
        b = buckets.setdefault(key, {"mes": key, "certificados": 0, "inscripciones": 0, "usuarios": 0})
        b[field] += 1

    for d in cert_dates:
        bump(d, "certificados")
    for d in enr_dates:
        bump(d, "inscripciones")
    for d in user_dates:
        bump(d, "usuarios")
    return sorted(buckets.values(), key=lambda x: x["mes"])


async def _task_submissions_rate(db, start, end, limit) -> list[dict]:
    # Tareas por curso
    tasks_stmt = (
        select(Course.id, func.count(LessonTask.id))
        .select_from(LessonTask)
        .join(Lesson, LessonTask.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .group_by(Course.id)
    )
    tasks = {r[0]: r[1] for r in (await db.execute(tasks_stmt)).all()}

    # Entregas por curso (en rango)
    sub_stmt = (
        select(Course.id, func.count(TaskSubmission.id))
        .select_from(TaskSubmission)
        .join(LessonTask, TaskSubmission.task_id == LessonTask.id)
        .join(Lesson, LessonTask.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .group_by(Course.id)
    )
    if start is not None:
        sub_stmt = sub_stmt.where(TaskSubmission.submitted_at >= start)
    if end is not None:
        sub_stmt = sub_stmt.where(TaskSubmission.submitted_at <= end)
    subs = {r[0]: r[1] for r in (await db.execute(sub_stmt)).all()}

    course_titles = {
        r[0]: r[1]
        for r in (await db.execute(select(Course.id, Course.title))).all()
    }
    out = []
    for cid, total in tasks.items():
        entregas = subs.get(cid, 0)
        out.append(
            {
                "curso": course_titles.get(cid, f"Curso #{cid}"),
                "tareas": total,
                "entregas": entregas,
                "porcentaje_entrega": round((entregas / total) * 100, 2) if total else 0,
            }
        )
    return sorted(out, key=lambda x: x["porcentaje_entrega"], reverse=True)[:limit]


# ── Registro / metadatos ────────────────────────────────────

REPORTS: dict[str, dict] = {
    "certificates_by_admin": {
        "title": "Emisiones por administrador y tipo",
        "description": "Qué administrador emitió qué certificado (tipo) a qué estudiante, en el rango.",
        "columns": [
            {"key": "fecha", "label": "Fecha"},
            {"key": "admin_id", "label": "Cód. admin"},
            {"key": "admin", "label": "Administrador"},
            {"key": "admin_email", "label": "Correo admin"},
            {"key": "tipo", "label": "Tipo"},
            {"key": "tipo_nombre", "label": "Nombre tipo"},
            {"key": "estudiante", "label": "Estudiante"},
            {"key": "estudiante_identidad", "label": "Documento"},
            {"key": "estudiante_email", "label": "Correo estudiante"},
            {"key": "uuid", "label": "UUID"},
            {"key": "estado", "label": "Estado"},
        ],
        "fn": _certificates_by_admin,
    },
    "certificates_by_type": {
        "title": "Certificados por tipo",
        "description": "Conteo de certificados (total y por estado) agrupado por tipo y en el rango.",
        "columns": [
            {"key": "tipo", "label": "Tipo"},
            {"key": "tipo_nombre", "label": "Nombre tipo"},
            {"key": "total", "label": "Total"},
            {"key": "activos", "label": "Activos"},
            {"key": "revocados", "label": "Revocados"},
            {"key": "expirados", "label": "Expirados"},
        ],
        "fn": _certificates_by_type,
    },
    "content_by_teacher": {
        "title": "Contenido por docente",
        "description": "Cursos, módulos, lecciones, evaluaciones y tareas por docente (cursos creados en el rango).",
        "columns": [
            {"key": "docente_id", "label": "Cód. docente"},
            {"key": "docente", "label": "Docente"},
            {"key": "email", "label": "Correo"},
            {"key": "cursos", "label": "Cursos"},
            {"key": "modulos", "label": "Módulos"},
            {"key": "lecciones", "label": "Lecciones"},
            {"key": "evaluaciones", "label": "Evaluaciones"},
            {"key": "tareas", "label": "Tareas"},
        ],
        "fn": _content_by_teacher,
    },
    "courses_assigned_by_user": {
        "title": "Cursos asignados por usuario",
        "description": "Cuántos y cuáles cursos fueron asignados a cada estudiante, en el rango.",
        "columns": [
            {"key": "estudiante_id", "label": "Cód. estudiante"},
            {"key": "estudiante", "label": "Estudiante"},
            {"key": "email", "label": "Correo"},
            {"key": "total_cursos", "label": "Total cursos"},
            {"key": "cursos", "label": "Cursos"},
        ],
        "fn": _courses_assigned_by_user,
    },
    "users_by_role": {
        "title": "Usuarios creados por rol",
        "description": "Cantidad de usuarios creados en el rango, agrupados por rol.",
        "columns": [
            {"key": "rol", "label": "Rol"},
            {"key": "cantidad", "label": "Cantidad"},
        ],
        "fn": _users_by_role,
    },
    "assessment_results": {
        "title": "Resultados de evaluaciones",
        "description": "Intentos, promedio, aprobados y % de aprobación por evaluación (fin en el rango).",
        "columns": [
            {"key": "curso", "label": "Curso"},
            {"key": "modulo", "label": "Módulo"},
            {"key": "evaluacion_id", "label": "Cód. evaluación"},
            {"key": "nota_minima", "label": "Nota mínima"},
            {"key": "intentos", "label": "Intentos"},
            {"key": "promedio", "label": "Promedio"},
            {"key": "aprobados", "label": "Aprobados"},
            {"key": "porcentaje_aprobacion", "label": "% Aprobación"},
        ],
        "fn": _assessment_results,
    },
    "certificates_status_flow": {
        "title": "Flujo de estados de certificados",
        "description": "Conteo de acciones sobre certificados (emitido, renovado, revocado, expirado…) en el rango.",
        "columns": [
            {"key": "accion", "label": "Acción"},
            {"key": "cantidad", "label": "Cantidad"},
        ],
        "fn": _certificates_status_flow,
    },
    "top_courses": {
        "title": "Cursos con más inscripciones",
        "description": "Top de cursos por número de inscripciones en el rango.",
        "columns": [
            {"key": "curso_id", "label": "Cód. curso"},
            {"key": "curso", "label": "Curso"},
            {"key": "inscritos", "label": "Inscritos"},
        ],
        "fn": _top_courses,
    },
    "task_submissions_rate": {
        "title": "Tasa de entrega de tareas por curso",
        "description": "Tareas, entregas y porcentaje de entrega por curso (entregas en el rango).",
        "columns": [
            {"key": "curso", "label": "Curso"},
            {"key": "tareas", "label": "Tareas"},
            {"key": "entregas", "label": "Entregas"},
            {"key": "porcentaje_entrega", "label": "% Entrega"},
        ],
        "fn": _task_submissions_rate,
    },
    "activity_monthly": {
        "title": "Actividad mensual",
        "description": "Serie por mes de certificados emitidos, inscripciones y usuarios creados.",
        "columns": [
            {"key": "mes", "label": "Mes"},
            {"key": "certificados", "label": "Certificados"},
            {"key": "inscripciones", "label": "Inscripciones"},
            {"key": "usuarios", "label": "Usuarios"},
        ],
        "fn": _activity_monthly,
    },
}


def catalog() -> list[dict]:
    return [
        {
            "key": key,
            "title": meta["title"],
            "description": meta["description"],
            "columns": meta["columns"],
        }
        for key, meta in REPORTS.items()
    ]

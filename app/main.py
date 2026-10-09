"""Aplicación FastAPI."""

import logging
import secrets
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.rate_limit import limiter

from app.core.database import AsyncSessionLocal, Base, engine
from app.core.logging_config import configure_logging, request_id_var
from app.core.security import get_password_hash
from app.core.settings import get_settings
from app.api.v1.router import ROUTERS as endpoint_routers
from app.models import (  # noqa: F401 — registra metadatos
    Certificate,
    CertificateAudit,
    CertificateType,
    Course,
    CourseEnrollment,
    Lesson,
    LessonTask,
    Module,
    User,
    UserProgress,
    WorkerAudit,
)
from app.models.system_log import SystemLog  # noqa: F401 — registra metadatos

configure_logging()

logger = logging.getLogger(__name__)


async def create_database_if_not_exists() -> None:
    """Crea la base de datos destino si no existe (solo para PostgreSQL)."""
    import re
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    db_url = settings.get_database_url()

    if not (db_url.startswith("postgresql") or db_url.startswith("postgres")):
        return

    # Parsear URL para conectarnos a la base de datos predeterminada 'postgres'
    match = re.match(r"^(postgresql(?:\+asyncpg)?://[^/]+/)([^?]+)(?:\?.*)?$", db_url)
    if not match:
        logger.warning("No se pudo parsear la URL de la base de datos para creación automática.")
        return

    base_url = match.group(1)
    db_name = match.group(2)

    postgres_url = f"{base_url}postgres"
    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql+asyncpg://", 1)

    temp_engine = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    try:
        async with temp_engine.connect() as conn:
            cleaned_db_name = re.sub(r"[^a-zA-Z0-9_]", "", db_name)
            if not cleaned_db_name:
                raise ValueError("El nombre de la base de datos es inválido.")

            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": cleaned_db_name}
            )
            exists = result.scalar()
            if not exists:
                logger.info("La base de datos '%s' no existe. Creando...", cleaned_db_name)
                await conn.execute(text(f'CREATE DATABASE "{cleaned_db_name}"'))
                logger.info("Base de datos '%s' creada exitosamente.", cleaned_db_name)
            else:
                logger.info("La base de datos '%s' ya existe.", cleaned_db_name)
    except Exception as e:
        logger.error("Error al verificar/crear la base de datos '%s': %s", db_name, e)
    finally:
        await temp_engine.dispose()


async def _seed_default_tenant(db) -> "Tenant":
    """Crea el tenant por defecto si no existe (modo single / retrocompat)."""
    from sqlalchemy import select

    from app.core.settings import get_settings
    from app.models.tenant import Tenant

    settings = get_settings()
    r = await db.execute(
        select(Tenant).where(Tenant.slug == settings.default_tenant_slug)
    )
    tenant = r.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            name=f"{settings.project_name} (predeterminado)",
            slug=settings.default_tenant_slug,
            is_active=True,
        )
        db.add(tenant)
        await db.flush()
        await db.refresh(tenant)
    return tenant


async def _seed_superuser() -> None:
    """Crea el superusuario inicial en el tenant por defecto si no existe."""
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        tenant = await _seed_default_tenant(session)
        result = await session.execute(
            select(User).where(
                User.email == settings.superuser_email,
                User.tenant_id == tenant.id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return

        superuser = User(
            email=settings.superuser_email,
            password_hash=get_password_hash(settings.superuser_password),
            name=settings.superuser_name,
            first_last_name=settings.superuser_first_last_name,
            role="superuser",
            identity_type=settings.superuser_identity_type,
            identity_number=settings.superuser_identity_number,
            phone_number=settings.superuser_phone_number,
            is_active=True,
            tenant_id=tenant.id,
        )
        session.add(superuser)
        await session.commit()
        logger.info("Superusuario '%s' creado.", settings.superuser_email)


async def _seed_system_bot(db_session=None) -> None:
    """Crea el usuario system bot del tenant por defecto si no existe.

    El bot se consulta por tenant porque hay un bot por cada organización.
    """
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        tenant = await _seed_default_tenant(session)
        result = await session.execute(
            select(User).where(
                User.email == settings.system_bot_user_email,
                User.tenant_id == tenant.id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return

        bot = User(
            email=settings.system_bot_user_email,
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            name=settings.system_bot_user_name,
            first_last_name=settings.system_bot_user_first_last_name,
            role="superuser",
            identity_type="OTHER",
            identity_number=f"BOT-{settings.system_bot_user_email}",
            phone_number=f"+000{abs(hash(settings.system_bot_user_email)) % 10_000_000_000:010d}",
            is_active=True,
            tenant_id=tenant.id,
        )
        session.add(bot)
        await session.commit()
        logger.info("System bot '%s' creado.", settings.system_bot_user_email)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await create_database_if_not_exists()
    if get_settings().auto_create_tables:
        # Solo para entornos de desarrollo/pruebas. En producción el esquema
        # se gestiona con Alembic (`alembic upgrade head`).
        logger.warning("AUTO_CREATE_TABLES activo: creando tablas desde los modelos.")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await _seed_superuser()
    await _seed_system_bot()
    yield
    await engine.dispose()



settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request: Request, exc: IntegrityError) -> JSONResponse:
    detail = str(exc.orig) if exc.orig else "Violación de restricción única"
    logger.warning("IntegrityError: %s", detail)
    return JSONResponse(
        status_code=409,
        content={"detail": "Ya existe un registro con ese valor"},
    )

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-cache, private"
    return response


async def _resolve_tenant_from_token(request: Request) -> int | None:
    """Lee el claim `tenant_id` del JWT (Bearer o cookie)."""
    from app.core.security import decode_token

    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else None
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        tid = payload.get("tenant_id")
        return int(tid) if tid else None
    except Exception:
        return None


async def _resolve_tenant_from_host(request: Request) -> int | None:
    """Resuelve el tenant por subdominio `{slug}.{ROOT_DOMAIN}` o dominio custom."""
    from sqlalchemy import or_, select

    from app.models.tenant import Tenant

    settings = get_settings()
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if not host or not settings.root_domain:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Tenant.id).where(
                or_(Tenant.slug == host, Tenant.domain == host)
            ).limit(1)
        )
        tenant_id = result.scalar_one_or_none()
        if tenant_id is not None:
            return int(tenant_id)
        if host.endswith("." + settings.root_domain) and len(host) > len(settings.root_domain):
            slug = host[: -(len(settings.root_domain) + 1)]
            if slug:
                result = await session.execute(
                    select(Tenant.id).where(Tenant.slug == slug).limit(1)
                )
                tenant_id = result.scalar_one_or_none()
                return int(tenant_id) if tenant_id is not None else None
    return None


@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    """Resuelve el tenant de la petición (JWT → subdominio → default)."""
    from app.core.tenant import make_tenant_token, reset_tenant_context

    tenant_id = await _resolve_tenant_from_token(request)
    if tenant_id is None:
        tenant_id = await _resolve_tenant_from_host(request)
    if tenant_id is None:
        # Sin contexto: get_db asignará el tenant por defecto.
        return await call_next(request)
    token = make_tenant_token(tenant_id)
    try:
        return await call_next(request)
    finally:
        reset_tenant_context(token)


async def _record_api_error(request: Request, request_id: str, exc: Exception | None, status_code: int) -> None:
    """Persiste en system_logs un error de la API. Silencioso."""
    from app.services.system_log_service import write_system_log

    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else None
    await write_system_log(
        level="error",
        source="api",
        event=f"{request.method} {request.url.path}",
        detail=str(exc) if exc else f"HTTP {status_code}",
        stacktrace=stack,
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        status_code=status_code,
    )


@app.middleware("http")
async def request_context_and_errors(request: Request, call_next):
    """Asigna un request_id, propaga el contexto y captura errores 500."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_var.set(request_id)
    is_health = request.url.path.rstrip("/").endswith("/health")
    try:
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — capturamos para registrar y devolver 500
            logger.exception("Error no manejado en %s %s", request.method, request.url.path)
            if not is_health:
                await _record_api_error(request, request_id, exc, status_code=500)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Error interno del servidor", "request_id": request_id},
            )
        else:
            if response.status_code >= 500 and not is_health:
                await _record_api_error(request, request_id, None, status_code=response.status_code)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response

for endpoint_router in endpoint_routers:
    app.include_router(endpoint_router, prefix=settings.api_v1_prefix)


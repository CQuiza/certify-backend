"""Aplicación FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, Base, engine
from app.core.security import get_password_hash
from app.core.settings import get_settings
from app.api.v1.router import api_router
from app.models import (  # noqa: F401 — registra metadatos
    Certificate,
    CertificateAudit,
    CertificateType,
    Course,
    CourseEnrollment,
    Lesson,
    Module,
    User,
    UserProgress,
)

logger = logging.getLogger(__name__)


async def _seed_superuser() -> None:
    """Crea el superusuario inicial si no existe."""
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == settings.superuser_email)
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
        )
        session.add(superuser)
        await session.commit()
        logger.info("Superusuario '%s' creado.", settings.superuser_email)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_superuser()
    yield
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


"""Entorno de Alembic (async) para Certify Backend.

La URL se toma de los settings de la app (``DATABASE_URL`` o ``POSTGRES_*``)
y se normaliza al driver async ``asyncpg``. Se importan los modelos para
registrar los metadatos y habilitar ``--autogenerate``.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 — registra todos los modelos en Base.metadata
from app.core.database import Base
from app.core.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _async_url() -> str:
    """Devuelve la URL normalizada al driver asyncpg."""
    url = get_settings().get_database_url()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Genera SQL sin conexión (modo offline)."""
    context.configure(
        url=_async_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Ejecuta las migraciones con una conexión async."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _async_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
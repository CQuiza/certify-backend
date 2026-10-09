"""Motor async, sesión (tenant-scoped) y Base declarativa."""

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, with_loader_criteria

from app.core.settings import get_settings

# Convención de nombres para constraints/índices. Garantiza nombres
# reproducibles y estables para las migraciones de Alembic. Las constraints
# existentes conservan su nombre explícito; esto aplica a las nuevas.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base para modelos ORM."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _async_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_settings = get_settings()
_url = _async_database_url(_settings.get_database_url())

# Para SQLite (solo pruebas): timeout + WAL evitan "database is locked"
# con sesiones concurrentes. En Postgres estos parámetros no se aplican.
_sqlite_connect_args = {"timeout": 30} if _url.startswith("sqlite") else {}
engine = create_async_engine(
    _url,
    echo=_settings.debug,
    pool_pre_ping=True,
    connect_args=_sqlite_connect_args or None,
)


def _with_tenant_criteria(statement):
    """Adjunta el filtro de tenant a statements ORM (via nuestra sesión).

    ``current_tenant_id()`` es ``None`` en contexto unscoped → no se filtra
    (operaciones globales del superadmin, workers globales, etc.).
    """
    from app.core.tenant import TenantScoped, current_tenant_id

    tenant_id = current_tenant_id()
    if tenant_id is None:
        return statement
    if not hasattr(statement, "options"):
        return statement
    try:
        return statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )
    except Exception:
        return statement


class TenantScopedAsyncSession(AsyncSession):
    """AsyncSession que inyecta el scope de tenant en cada ejecución."""

    async def execute(self, statement, params=None, *, execution_options=None, **kw):  # type: ignore[override]
        statement = _with_tenant_criteria(statement)
        kwargs: dict = {}
        if execution_options is not None:
            kwargs["execution_options"] = execution_options
        return await super().execute(statement, params=params, **kwargs, **kw)


def _set_tenant_on_insert(session: Session, flush_context, instances) -> None:
    """Rellena `tenant_id` en las inserciones de modelos tenanted.

    Los selects se filtran con `with_loader_criteria`; esta evento cubre los
    `INSERT`: cualquier objeto `TenantScoped` nuevo sin tenant se asigna al
    tenant activo del contexto. En contexto unscoped no se toca (quien inserte
    debe fijar el tenant explícitamente).
    """
    from app.core.tenant import TenantScoped, current_tenant_id

    tenant_id = current_tenant_id()
    if tenant_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScoped) and getattr(obj, "tenant_id", None) is None:
            obj.tenant_id = tenant_id


event.listen(Session, "before_flush", _set_tenant_on_insert)


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=TenantScopedAsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    from app.core.tenant import ensure_current_tenant

    async with AsyncSessionLocal() as session:
        try:
            await ensure_current_tenant(session)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_unscoped() -> AsyncGenerator[AsyncSession, None]:
    """Sesión sin filtro de tenant (panel superadmin / operaciones globales)."""
    from app.core.tenant import make_tenant_token, reset_tenant_context

    async with AsyncSessionLocal() as session:
        token = make_tenant_token(None)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            reset_tenant_context(token)
            await session.close()
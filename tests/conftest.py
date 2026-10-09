"""Configuración de pruebas con base de datos SQLite.

Las variables de entorno se fijan ANTES de importar la app para que el engine
async y los settings apunten a SQLite y no a PostgreSQL. Todas las pruebas
comparten un único event-loop de sesión (ver pytest.ini).
"""

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_certify.db"
os.environ["SECRET_KEY"] = "test-secret-key-change-me"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "false"
os.environ["PROJECT_NAME"] = "Certify"
os.environ["LOKI_URL"] = ""
os.environ["LOG_FORMAT"] = "text"
os.environ["ALLOWED_HOSTS"] = '["*"]'
os.environ["CORS_ORIGINS"] = '["http://localhost:3000"]'
os.environ["SUPERUSER_EMAIL"] = "super@test.local"
os.environ["SUPERUSER_PASSWORD"] = "TestPassw0rd!!"
os.environ["SUPERUSER_NAME"] = "Super"
os.environ["SUPERUSER_FIRST_LAST_NAME"] = "Usuario"
os.environ["SYSTEM_BOT_USER_EMAIL"] = "system@test.local"
os.environ["DEFAULT_TENANT_SLUG"] = "default"
os.environ["ROOT_DOMAIN"] = "testserver"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from sqlalchemy import delete as sql_delete  # noqa: E402
from sqlalchemy import select  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402

SUPERUSER_EMAIL = os.environ["SUPERUSER_EMAIL"]
SUPERUSER_PASSWORD = os.environ["SUPERUSER_PASSWORD"]
SYSTEM_BOT_EMAIL = os.environ["SYSTEM_BOT_USER_EMAIL"]
STUDENT_EMAIL = "student@test.local"
STUDENT_PASSWORD = "StudentPass1!"
DEFAULT_SLUG = os.environ["DEFAULT_TENANT_SLUG"]


async def _default_tenant_id() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant.id).where(Tenant.slug == DEFAULT_SLUG))
        tenant_id = result.scalar_one_or_none()
        if tenant_id is None:
            t = Tenant(name="Predeterminado", slug=DEFAULT_SLUG, is_active=True)
            session.add(t)
            await session.commit()
            await session.refresh(t)
            tenant_id = t.id
        return int(tenant_id)


async def _seed_user(
    *,
    email: str,
    password: str,
    name: str,
    role: str,
    identity_number: str,
    phone_number: str,
    tenant_id: int,
) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is None:
            session.add(
                User(
                    email=email,
                    password_hash=get_password_hash(password),
                    name=name,
                    first_last_name="Prueba",
                    role=role,
                    identity_type="CC",
                    identity_number=identity_number,
                    phone_number=phone_number,
                    is_active=True,
                    tenant_id=tenant_id,
                )
            )
            await session.commit()


@pytest.fixture(scope="session", autouse=True)
async def _prepare_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    default_id = await _default_tenant_id()
    await _seed_user(
        email=SUPERUSER_EMAIL,
        password=SUPERUSER_PASSWORD,
        name="Super",
        role="superuser",
        identity_number="2020202020",
        phone_number="+570000000001",
        tenant_id=default_id,
    )
    await _seed_user(
        email=SYSTEM_BOT_EMAIL,
        password="",
        name="System",
        role="superuser",
        identity_number="2020202021",
        phone_number="+570000000002",
        tenant_id=default_id,
    )
    yield


@pytest.fixture(autouse=True)
async def _clean_platform_settings():
    """Aísla los tests: sin filas de configuración previas de otros tests."""
    from app.models.email_template import EmailTemplate
    from app.models.platform_settings import PlatformSettings

    async with AsyncSessionLocal() as session:
        await session.execute(sql_delete(EmailTemplate))
        await session.execute(sql_delete(PlatformSettings))
        await session.commit()
    yield


@pytest.fixture
async def db():
    from app.core.tenant import tenant_ctx

    default_id = await _default_tenant_id()
    async with AsyncSessionLocal() as session:
        async with tenant_ctx(default_id):
            yield session


@pytest.fixture
async def client():
    # Sin lifespan (la app siembra los usuarios en _prepare_db); usamos
    # ASGITransport para ejecutar las rutas en el mismo event-loop de pytest.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
async def superuser_token() -> str:
    # El login está limitado a 10/min: se hace una sola vez por sesión.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        return await _login(ac, SUPERUSER_EMAIL, SUPERUSER_PASSWORD)


@pytest.fixture(scope="session")
async def tenant_b_credentials() -> tuple[str, str, str]:
    """Crea el tenant 'acme' con su admin; devuelve (slug, email, password)."""
    from app.services.tenant_service import tenant_service

    password = "TenantAdmin123!"
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(Tenant).where(Tenant.slug == "acme"))
        if existing.scalar_one_or_none() is None:
            await tenant_service.create_tenant(
                session,
                name="ACME Corp",
                slug="acme",
                admin_email="admin@acme.example",
                admin_name="Admin ACME",
                admin_password=password,
            )
            await session.commit()
    return "acme", "admin@acme.example", password


@pytest.fixture(scope="session")
async def tenant_b_admin_token(tenant_b_credentials) -> str:
    _, email, password = tenant_b_credentials
    # El admin entra por su subdominio: {slug}.{ROOT_DOMAIN}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://acme.{os.environ['ROOT_DOMAIN']}"
    ) as ac:
        return await _login(ac, email, password)


@pytest.fixture(scope="session")
async def student_token() -> str:
    from app.models.user import User

    default_id = await _default_tenant_id()
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(User).where(User.email == STUDENT_EMAIL))
        if existing.scalar_one_or_none() is None:
            session.add(
                User(
                    email=STUDENT_EMAIL,
                    password_hash=get_password_hash(STUDENT_PASSWORD),
                    name="Estudiante",
                    first_last_name="Prueba",
                    role="student",
                    identity_type="CC",
                    identity_number="1010101010",
                    phone_number="+570000000011",
                    is_active=True,
                    tenant_id=default_id,
                )
            )
            await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        return await _login(ac, STUDENT_EMAIL, STUDENT_PASSWORD)
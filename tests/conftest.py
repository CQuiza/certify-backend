"""Configuración de pruebas con base de datos SQLite en memoria.

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
os.environ["ALLOWED_HOSTS"] = '["testserver", "localhost", "127.0.0.1"]'
os.environ["CORS_ORIGINS"] = '["http://localhost:3000"]'
os.environ["SUPERUSER_EMAIL"] = "super@test.local"
os.environ["SUPERUSER_PASSWORD"] = "TestPassw0rd!!"
os.environ["SUPERUSER_NAME"] = "Super"
os.environ["SUPERUSER_FIRST_LAST_NAME"] = "Usuario"
os.environ["SYSTEM_BOT_USER_EMAIL"] = "system@test.local"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from sqlalchemy import delete as sql_delete  # noqa: E402
from sqlalchemy import select  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

SUPERUSER_EMAIL = os.environ["SUPERUSER_EMAIL"]
SUPERUSER_PASSWORD = os.environ["SUPERUSER_PASSWORD"]
SYSTEM_BOT_EMAIL = os.environ["SYSTEM_BOT_USER_EMAIL"]
STUDENT_EMAIL = "student@test.local"
STUDENT_PASSWORD = "StudentPass1!"


async def _seed_user(
    *,
    email: str,
    password: str,
    name: str,
    role: str,
    identity_number: str,
    phone_number: str,
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
                )
            )
            await session.commit()


@pytest.fixture(scope="session", autouse=True)
async def _prepare_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_user(
        email=SUPERUSER_EMAIL,
        password=SUPERUSER_PASSWORD,
        name="Super",
        role="superuser",
        identity_number="2020202020",
        phone_number="+570000000001",
    )
    await _seed_user(
        email=SYSTEM_BOT_EMAIL,
        password="",
        name="System",
        role="superuser",
        identity_number="2020202021",
        phone_number="+570000000002",
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
    async with AsyncSessionLocal() as session:
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
async def student_token() -> str:
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
                )
            )
            await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        return await _login(ac, STUDENT_EMAIL, STUDENT_PASSWORD)
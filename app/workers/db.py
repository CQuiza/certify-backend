"""Motor y sesión async exclusivos del worker (Celery).

Cada tarea del worker se ejecuta con ``asyncio.run`` (un event loop nuevo por
tarea). Con el engine compartido y su pool, las conexiones de asyncpg quedan
ligadas al loop que las creó y al reutilizarlas entre tareas se produce el error
"got Future attached to a different loop".

Por eso el worker usa su propio engine con ``NullPool``: no se conservan
conexiones entre ejecuciones, cada ``asyncio.run`` abre y cierra la suya en su
propio loop.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import TenantScopedAsyncSession, _async_database_url
from app.core.settings import get_settings

_settings = get_settings()
_url = _async_database_url(_settings.get_database_url())

# En SQLite (solo pruebas) el timeout evita "database is locked".
_sqlite_connect_args = {"timeout": 30} if _url.startswith("sqlite") else {}

worker_engine = create_async_engine(
    _url,
    echo=_settings.debug,
    poolclass=NullPool,
    connect_args=_sqlite_connect_args or None,
)

WorkerSessionLocal = async_sessionmaker(
    worker_engine,
    class_=TenantScopedAsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

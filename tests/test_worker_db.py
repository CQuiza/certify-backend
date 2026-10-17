"""El worker usa su propia sesión con NullPool (sin conexiones entre loops).

Cada tarea corre con ``asyncio.run`` (loop nuevo). Con NullPool no se reutilizan
conexiones entre ejecuciones, evitando el error de asyncpg
"got Future attached to a different loop".
"""

import asyncio

from sqlalchemy import text

from app.workers.db import WorkerSessionLocal


def test_worker_session_survives_multiple_event_loops():
    """Dos asyncio.run seguidos (loops distintos) no deben reutilizar conexiones."""

    async def _ping() -> None:
        async with WorkerSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            await session.commit()

    asyncio.run(_ping())
    asyncio.run(_ping())

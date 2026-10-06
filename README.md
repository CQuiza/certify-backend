# Certify Backend

Este es el backend para la plataforma **Certify**, construido con **FastAPI**, **SQLAlchemy** (async) y **PostgreSQL**.

## Características Principales

El proyecto gestiona las siguientes entidades:
- **Usuarios (Users) y Autenticación**
- **Cursos (Courses)**
- **Módulos (Modules)**
- **Lecciones (Lessons)**
- **Inscripciones (Course Enrollments)**
- **Progreso del Usuario (User Progress)**
- **Certificados (Certificates)** y sus **Tipos (Certificate Types)**
- **Auditoría de Certificados (Certificate Audit)**

## Requisitos

- Python 3.10+
- `uv` (Recomendado para manejar paquetes y el entorno virtual)
- PostgreSQL (opcional para desarrollo local, soporta SQLite temporal)

## Instalación y Configuración

1. **Clonar o descargar** el repositorio.
2. **Crear y activar entorno virtual**:
   ```bash
   uv venv
   source .venv/bin/activate
   ```
3. **Instalar dependencias**:
   ```bash
   uv pip sync requirements.txt
   ```
4. **Variables de entorno**:
   Copia el archivo `.env.example` a `.env` y configura los valores (por ejemplo, `DATABASE_URL`, JWT secret, etc.).
   ```bash
   cp .env.example .env
   ```

## Ejecución

1. **Crear la base de datos** si no existe (ver sección *Crear la base de datos
   desde la app*).
2. **Aplicar migraciones** (crea/actualiza el esquema):
   ```bash
   alembic upgrade head
   ```
3. Iniciar el servidor de desarrollo con el CLI de FastAPI o Uvicorn:

```bash
fastapi dev app/main.py
```
O usando uvicorn directamente:
```bash
uvicorn app.main:app --reload
```

## Crear la base de datos desde la app

El backend incluye `create_database_if_not_exists()` en `app/main.py`, que
conecta a la BD `postgres` y crea la base de datos destino si no existe
(útil tras borrar/recrear la BD de desarrollo). Se ejecuta al arrancar la API,
o manualmente con un one-off:

```bash
# local (docker compose dev)
docker compose -f docker-compose.dev.yml run --rm --no-deps --entrypoint python migrate -c \
  "import asyncio; from app.main import create_database_if_not_exists; asyncio.run(create_database_if_not_exists())"

# producción (docker compose, en el servidor)
docker compose run --rm --no-deps --entrypoint python migrate -c \
  "import asyncio; from app.main import create_database_if_not_exists; asyncio.run(create_database_if_not_exists())"
```

> Tras crear la BD, ejecuta `alembic upgrade head` para construir el esquema.

## Migraciones (Alembic)

El esquema de base de datos se gestiona con **Alembic** (`alembic/`). La URL se
resuelve desde los settings (`DATABASE_URL` o `POSTGRES_*`); no se fija en
`alembic.ini`.

Local se usa `docker compose -f docker-compose.dev.yml`; en producción (servidor)
`docker compose` a secas (allí el archivo es `docker-compose.yml`). Todos los
comandos de Alembic se ejecutan con el servicio `migrate`:

| Acción | Comando |
| --- | --- |
| Aplicar todas las migraciones | `docker compose [-f docker-compose.dev.yml] run --rm migrate alembic upgrade head` |
| Revisión aplicada | `... run --rm migrate alembic current -v` |
| Última revisión (head) | `... run --rm migrate alembic heads` |
| Historial | `... run --rm migrate alembic history --verbose` |
| Detalle de una revisión | `... run --rm migrate alembic show <rev>` |
| Detectar drift (modelos vs BD) | `... run --rm migrate alembic check` |
| Crear migración (autogenerate) | `... run --rm migrate alembic revision --autogenerate -m "descripcion"` |
| Crear migración manual | `... run --rm migrate alembic revision -m "descripcion"` |
| Revertir la última | `... run --rm migrate alembic downgrade -1` |
| Marcar una revisión sin ejecutarla | `... run --rm migrate alembic stamp <rev>` |
| SQL offline (sin ejecutar) | `... run --rm migrate alembic upgrade <base>:head --sql` |
| Combinar ramas | `... run --rm migrate alembic merge -m "merge" <rev1> <rev2>` |

Ejemplo de flujo ante un cambio de modelo (local):

```bash
# 1. Asegurar que la BD de dev está al día
docker compose -f docker-compose.dev.yml run --rm migrate alembic upgrade head
# 2. Verificar que NO hay drift previo (debe decir "No new upgrade operations detected")
docker compose -f docker-compose.dev.yml run --rm migrate alembic check
# 3. Generar la migración y revisarla
docker compose -f docker-compose.dev.yml run --rm migrate alembic revision --autogenerate -m "descripcion"
# 4. Aplicar en dev
docker compose -f docker-compose.dev.yml run --rm migrate alembic upgrade head
```

Notas:
- `alembic/versions/0001_baseline.py` es el **baseline** que reproduce el
  esquema de producción (alineado al ORM). En una base de datos que **ya**
  tiene el esquema (p. ej. producción) no se debe ejecutar el baseline: en su
  lugar se marca como aplicado con `alembic stamp 0001_baseline`.
- **Nunca** generes una migración contra una BD con drift (una BD que no
  coincide con los modelos): el diff saldrá incorrecto. Usa `alembic check`.
- `model.db` es un **esquema de referencia** (DDL alineado al ORM). La fuente
  canónica versionada es Alembic.
- En desarrollo, la creación automática de tablas desde el ORM está disponible
  con `AUTO_CREATE_TABLES=true`, pero **no** debe usarse en producción.
- Los archivos SQL en `app/migrations/` son **históricos** (previos a Alembic);
  se conservan solo como referencia.

### Adopción en una base de datos existente (producción)

```bash
# 1. Backup previo
pg_dump "$DATABASE_URL" > backup.sql
# 2. Marcar el baseline como aplicado (NO ejecutarlo)
alembic stamp 0001_baseline
# 3. Verificar
alembic current
```

A partir de ese momento, cada despliegue aplica `alembic upgrade head`.

## Documentación de la API

Una vez que la aplicación esté corriendo, la documentación interactiva generada por FastAPI estará disponible en:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

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

1. **Aplicar migraciones** (crea/actualiza el esquema):
   ```bash
   alembic upgrade head
   ```
2. Iniciar el servidor de desarrollo con el CLI de FastAPI o Uvicorn:

```bash
fastapi dev app/main.py
```
O usando uvicorn directamente:
```bash
uvicorn app.main:app --reload
```

## Migraciones (Alembic)

El esquema de base de datos se gestiona con **Alembic** (`alembic/`). La URL se
resuelve desde los settings (`DATABASE_URL` o `POSTGRES_*`); no se fija en
`alembic.ini`.

Comandos habituales:

```bash
alembic upgrade head                      # aplicar todas las migraciones
alembic downgrade -1                      # revertir la última
alembic revision --autogenerate -m "msg"  # nueva migración desde los modelos
alembic current                           # revisión aplicada
alembic history                           # historial
```

Notas:
- `alembic/versions/0001_baseline.py` es el **baseline** que reproduce el
  esquema de producción (alineado al ORM). En una base de datos que **ya**
  tiene el esquema (p. ej. producción) no se debe ejecutar el baseline: en su
  lugar se marca como aplicado con `alembic stamp 0001_baseline`.
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

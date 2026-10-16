# Certify / Acreditapp — Backend

Backend de **Acreditapp**, una infraestructura **SaaS multitenant** (white-label) para gestionar, vender, dictar y certificar capacitaciones corporativas y educación complementaria/informal.

Construido con **FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL**, **Alembic**, **MinIO** (S3-compatible), **Celery + RabbitMQ** y **fastapi-mail**. API bajo el prefijo `/api/v1`.

---

## Tabla de contenido

- [Arquitectura](#arquitectura)
- [Modelo de dominio](#modelo-de-dominio)
- [Roles y multitenancy](#roles-y-multitenancy)
- [Módulos funcionales](#módulos-funcionales)
- [Superficie de la API](#superficie-de-la-api)
- [Requisitos e instalación](#requisitos-e-instalación)
- [Ejecución](#ejecución)
- [Configuración y variables de entorno](#configuración-y-variables-de-entorno)
- [Almacenamiento de archivos y migración a R2](#almacenamiento-de-archivos-y-migración-a-r2)
- [Migraciones (Alembic)](#migraciones-alembic)
- [Monitorización (logs y errores)](#monitorización-logs-y-errores)
- [Personalización de la plataforma (/configuration)](#personalización-de-la-plataforma-configuration)
- [Pruebas](#pruebas)
- [Documentación de la API](#documentación-de-la-api)
- [Notas y limitaciones conocidas](#notas-y-limitaciones-conocidas)

---

## Arquitectura

El backend sigue una separación por capas:

- **Endpoints** (`app/api/v1/endpoints/`): capa HTTP delgada (validación, RBAC, serialización).
- **Servicios** (`app/services/`): orquestación de casos de uso (ciclo de vida de certificados, pagos, configuración, notificaciones, reportes).
- **Repositorios** (`app/repositories/`): acceso a datos (singletons por entidad).
- **Modelos** (`app/models/`) y **Esquemas** (`app/schemas/`): ORM SQLAlchemy y contratos Pydantic.

Componentes transversales: multitenancy (`app/core/tenant.py`), seguridad (`app/core/security.py`), cifrado de secretos (`app/core/crypto.py`), rate limiting (`app/core/rate_limit.py`), logging/monitorización (`app/core/logging_config.py`) y workers Celery (`app/workers/`).

En el arranque (`app/main.py`): crea la base de datos si no existe (PostgreSQL), opcionalmente crea tablas (`AUTO_CREATE_TABLES`), y siembra el tenant por defecto, el superusuario y un *system bot* por tenant.

## Modelo de dominio

Todas las tablas de negocio heredan de `TenantScoped` (añade `tenant_id`).

**Identidad y organización**
- `tenants`, `users`, `platform_settings`, `email_templates`.

**Contenido educativo**
- `courses` (estado draft/published/archived, precio, renovación, `image_object_key`), `course_enrollments`.
- `modules`, `lessons`, `lesson_files`, `lesson_tasks`, `task_submissions`.
- `module_assessments`, `assessment_questions`, `assessment_options`, `user_assessment_attempts`, `user_assessment_answers`.
- `user_progress`.

**Certificación**
- `certificates` (UUID, QR, vigencia, estado active/revoked/expired), `certificate_types`, `certificate_audit`, `pending_certificates` (en proceso / renovación).

**Pagos**
- `course_orders`, `course_order_items` (Mercado Pago Checkout Pro).

**Auditoría y observabilidad**
- `email_audit`, `user_audit`, `worker_audit`, `system_logs`.

## Roles y multitenancy

Roles (`app/models/enums.py`): `superuser`, `admin`, `teacher`, `student`. El control de acceso es a nivel de aplicación (`app/services/access.py` + guardas por endpoint).

| Rol | Alcance |
|---|---|
| **superuser** | Global (todas las organizaciones): gestión de tenants, impersonación, configuración de plataforma, monitoreo, todo el RBAC. Único que crea/edita superusuarios. |
| **admin** | Dentro de su organización: usuarios (excepto superusuarios), cursos, módulos/lecciones/tareas/evaluaciones, inscripciones, certificados, tipos, reportes, auditoría. |
| **teacher** | Solo sus cursos: contenido, tareas, evaluaciones, calificación de entregas, inscripción de estudiantes de sus cursos. |
| **student** | Consume cursos inscritos/comprados, entrega tareas, presenta evaluaciones, consulta progreso y certificados, autoservicio de renovación. |

**Aislamiento multitenant** (sin RLS de PostgreSQL): un `ContextVar` (`current_tenant_id`) más un `AsyncSession` personalizado inyecta `with_loader_criteria(tenant_id == …)` en cada consulta ORM y estampa `tenant_id` al insertar. La resolución del tenant sigue el orden: claim `tenant_id` del JWT → impersonación del superusuario (`X-Acting-Tenant` / cookie) → host (`{slug}.{ROOT_DOMAIN}` o dominio custom) → tenant por defecto.

## Módulos funcionales

### Certificados
Ciclo de vida completo (`app/services/certificate_lifecycle.py`):
- **Emisión** manual o automática (certificados **pendientes** ligados a un curso que se emiten al completar el 100%).
- **PDF + QR**: overlay con ReportLab sobre una plantilla base, QR con la URL pública de verificación; subida a MinIO.
- **Verificación pública**: `GET /certificates/view/{uuid}` (PDF) y `/qr` (PNG); búsqueda por identidad `GET /certificates/search-by-identity/{n}`.
- **Revocación / reactivación / expiración** (worker) con marcas de agua y auditoría.
- **Renovación**: reasigna el curso, reinicia progreso y reactiva el mismo UUID al recompletar; autoservicio del estudiante con/sin pago.
- **Regla de "completado"**: cada módulo requiere (sin evaluación **o** aprobada) **y** (sin tareas **o** todas entregadas).

### Evaluaciones por módulo
- Tipos: `multiple_choice` (≥2 opciones, 1 correcta) y `true_false` (2 opciones, 1 correcta); validado en el esquema.
- `passing_score` (1–100). Intentos ilimitados; puntaje ponderado por `points`; opciones mezcladas para el estudiante.

### Tareas y entregas
- Tareas por lección (archivo en MinIO o enlace de Google Drive).
- El estudiante entrega **un único PDF** por tarea (un intento); el docente califica con nota (0–100) y retroalimentación.

### Archivos de lección e imagen de curso
- Archivos de lección en MinIO (extensiones `jpg, png, pdf, docx, pptx, xlsx`).
- Imagen de curso: validada con Pillow, redimensionada a WebP (máx. 1200 px, ≤5 MB), servida públicamente (proxy o redirección a `MEDIA_PUBLIC_BASE_URL`).

### Pagos (Mercado Pago Checkout Pro)
- `POST /payments/checkout` (compra de cursos) y `POST /payments/renew/{certificate_id}` (renovación; gratis si el precio de renovación es 0).
- Webhook público + **reconciliación server-to-server** (`GET /payments/orders/{id}`) para aprobar pagos sin depender del webhook.
- Marketplace split opcional por tenant (comisión de plataforma).

### Correo
- `fastapi-mail`; SMTP configurable por tenant en BD (contraseña cifrada con Fernet) con *fallback* al `.env`.
- Plantillas con placeholders (`credentials`, `certificate_issued`, `certificate_expired`) y logo inline; auditoría en `email_audit`.

### Reportes y dashboard
- Registro de reportes (`app/services/report_service.py`) con columnas, gráficas y exportación a CSV.
- `GET /dashboard/stats` y `GET /dashboard/admins`.

### Workers (Celery + RabbitMQ)
- `check_expired_certificates` (diario): marca vencidos, aplica marca de agua, desinscribe, audita y notifica.
- `backup_database_to_minio` (diario): `pg_dump` a MinIO.

### Monitoreo
- `system_logs` (api/worker/frontend) con `request_id` correlacionable; `GET /monitoring/logs` (superusuario) e ingestión desde el frontend.

## Superficie de la API

Todos los routers se montan bajo `/api/v1` (`app/api/v1/router.py`). Resumen:

| Área | Prefijo | Ejemplos |
|---|---|---|
| Autenticación | — | `/auth/register`, `/auth/token`, `/auth/refresh`, `/auth/logout`, `/auth/me` |
| Usuarios | `/users` | CRUD, `/users/certified`, `/users/change-password` |
| Cursos | `/courses` | CRUD, `/courses/{id}/image` (POST/DELETE/GET) |
| Módulos | `/modules` | CRUD (lista con `has_assessment`) |
| Lecciones / archivos | `/lessons` | CRUD, `/lessons/{id}/files/...` |
| Tareas / entregas | `/tasks`, — | `/tasks/by-lesson/{id}`, `/tasks/{id}/submit`, `/submissions/{id}/grade` |
| Evaluaciones | — | `/modules/{id}/assessment`, `/assessments/{id}/submit`, `/user-progress/summary[/{course_id}]` |
| Progreso | `/user-progress` | CRUD de progreso de lecciones |
| Certificados | `/certificates` | emisión, `/batch`, `/pending`, `/{id}/renew`, `/view/{uuid}`, `/search-by-identity/{n}` |
| Tipos de certificado | `/certificate-types` | CRUD |
| Inscripciones | `/course-enrollments` | listar, crear, eliminar |
| Pagos | `/payments` | `/checkout`, `/renew/{id}`, `/orders/{id}`, `/webhook` |
| Configuración | `/configuration` | branding, SMTP, plantillas, pagos, plantilla de certificado |
| Reportes / dashboard | `/reports`, `/dashboard` | catálogo de reportes, stats |
| Monitoreo | `/monitoring` | logs (GET/POST) |
| Administración | `/admin/tenants` | tenants, impersonación |
| Auditoría | `/certificate-audit`, `/user-audit`, `/worker-audit`, `/email-audit` | listados |
| Salud | — | `/health`, `/health/workers` |

## Requisitos e instalación

- **Python 3.11+** (la imagen Docker usa 3.12; el código usa `datetime.UTC`).
- **PostgreSQL** (los tests usan SQLite).
- **MinIO** (S3-compatible), **RabbitMQ** (workers).
- `uv` (recomendado) o `pip`.

```bash
# Entorno
uv venv && source .venv/bin/activate      # o: python -m venv .venv
uv pip sync requirements.txt              # o: pip install -r requirements.txt

# Variables de entorno
cp .env.example .env
```

## Ejecución

1. Crear la base de datos si no existe (ver *Crear la base de datos desde la app*).
2. Aplicar migraciones: `alembic upgrade head`.
3. Servidor de desarrollo:

```bash
fastapi dev app/main.py
# o
uvicorn app.main:app --reload
```

### Crear la base de datos desde la app

`create_database_if_not_exists()` en `app/main.py` conecta a la BD `postgres` y crea la base destino si no existe (útil tras borrar/recrear la BD de desarrollo). Se ejecuta al arrancar la API, o con un one-off:

```bash
# local (docker compose dev)
docker compose -f docker-compose.dev.yml run --rm --no-deps --entrypoint python migrate -c \
  "import asyncio; from app.main import create_database_if_not_exists; asyncio.run(create_database_if_not_exists())"

# producción (docker compose, en el servidor)
docker compose run --rm --no-deps --entrypoint python migrate -c \
  "import asyncio; from app.main import create_database_if_not_exists; asyncio.run(create_database_if_not_exists())"
```

> Tras crear la BD, ejecuta `alembic upgrade head` para construir el esquema.

## Configuración y variables de entorno

Se resuelven con Pydantic `BaseSettings` (`app/core/settings.py`, `env_file=".env"`). Grupos principales (ver `.env.example` para la lista completa):

- **Base de datos**: `DATABASE_URL` o `POSTGRES_USER/PASSWORD/DB/HOST/PORT`; `AUTO_CREATE_TABLES` (solo dev).
- **Seguridad**: `SECRET_KEY` (también clave de cifrado de secretos), `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `BCRYPT_ROUNDS`.
- **Dominio/tenant**: `ROOT_DOMAIN` (vacío = single-tenant; si no, `{slug}.{ROOT_DOMAIN}`), `DEFAULT_TENANT_SLUG`, `BASE_URL`.
- **Superusuario / bot**: `SUPERUSER_*`, `SYSTEM_BOT_USER_*`.
- **MinIO**: `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET`, `MINIO_PATH_*` (pdf, qr, tasks, lesson files, submissions, certificate template, branding, course images, backups), `MINIO_SECURE`, `MINIO_REGION`, `MEDIA_PUBLIC_BASE_URL`.
- **Correo (fallback)**: `SMTP_HOST/PORT/USER/PASSWORD/TLS`, `EMAIL_FROM` (los tenants pueden sobrescribir en BD).
- **Pagos**: `MERCADOPAGO_ACCESS_TOKEN/PUBLIC_KEY/WEBHOOK_SECRET`, `PAYMENTS_ENABLED`, `PAYMENTS_CURRENCY`, `PLATFORM_COMMISSION_PERCENT/FIXED`.
- **Runtime/observabilidad**: `ENVIRONMENT`, `DEBUG`, `LOG_FORMAT` (`text`|`json`), `LOKI_URL`, `LOG_SOURCE`.
- **CORS/hosts**: `CORS_ORIGINS`, `ALLOWED_HOSTS`, `API_V1_PREFIX`.
- **Uploads/workers**: `TASK_MAX_UPLOAD_SIZE_MB`, `LESSON_FILE_MAX_UPLOAD_SIZE_MB`, `CHECK_EXPIRED_INTERVAL_HOURS`, `RABBITMQ_URL`.

> El panel `/configuration` permite gestionar marca, SMTP, plantillas, pagos y plantilla de certificado **por organización** (solo superusuario), sin tocar el `.env`.

## Almacenamiento de archivos y migración a R2

Todo el acceso a objetos pasa por `app/utils/minio_client.py` (SDK `minio`, **S3-compatible**), por lo que migrar a **Cloudflare R2** (u otro S3-compatible) es un cambio de **configuración**, no de código:

```env
MINIO_ENDPOINT=<cuenta>.r2.cloudflarestorage.com
MINIO_ACCESS_KEY=...        # R2 access key
MINIO_SECRET_KEY=...        # R2 secret key
MINIO_BUCKET=<bucket>
MINIO_SECURE=true
MINIO_REGION=auto
# Opcional: servir media directo (egress $0 en R2)
MEDIA_PUBLIC_BASE_URL=https://media.tudominio.com
```

- Se usa un **único bucket** organizado por prefijos (`certifications/pdf`, `certifications/qr`, `tasks/files`, `tasks/submissions`, `lessons/files`, `courses/images`, `certificate/template`, `platform/branding`, `backup/...`). `ensure_bucket()` es idempotente.
- Si `MEDIA_PUBLIC_BASE_URL` está definida, los GET de media (p. ej. imagen de curso) redirigen a `{base}/{object_key}`; si no, se sirven por *proxy* desde el backend.

## Migraciones (Alembic)

El esquema se gestiona con **Alembic** (`alembic/`). La URL se resuelve desde los settings; no se fija en `alembic.ini`.

Local: `docker compose -f docker-compose.dev.yml`; producción: `docker compose`. Los comandos se ejecutan con el servicio `migrate`:

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

Flujo ante un cambio de modelo (local):

```bash
docker compose -f docker-compose.dev.yml run --rm migrate alembic upgrade head
docker compose -f docker-compose.dev.yml run --rm migrate alembic check
docker compose -f docker-compose.dev.yml run --rm migrate alembic revision --autogenerate -m "descripcion"
docker compose -f docker-compose.dev.yml run --rm migrate alembic upgrade head
```

Notas:
- `alembic/versions/0001_baseline.py` es el **baseline** alineado al ORM. En una BD que ya tiene el esquema (producción) **no** se ejecuta: se marca con `alembic stamp 0001_baseline`.
- **Nunca** generes una migración contra una BD con drift: verifica con `alembic check`.
- `model.db` es un esquema de referencia (DDL); la fuente canónica es Alembic.
- `AUTO_CREATE_TABLES=true` solo en desarrollo.
- Los SQL en `app/migrations/` son históricos (pre-Alembic), solo referencia.

Adopción en una BD existente (producción):

```bash
pg_dump "$DATABASE_URL" > backup.sql
alembic stamp 0001_baseline
alembic current
```

## Monitorización (logs y errores)

Los eventos/errores se registran en **`system_logs`** (`write_system_log` + middleware de `main.py`) y se exponen en `GET /monitoring/logs` (solo **superuser**); en el frontend se ven en el panel **Monitoreo** (`/monitoring`).

- **Origen** (`source`): `api`, `worker`, `frontend`.
- **Nivel** (`level`): `debug`, `info`, `warning`, `error`, `critical`.
- Cada petición lleva un `request_id` (header `X-Request-ID`) propagado a logs y `system_logs`.
- Errores 500 de la API y errores de render del frontend se persisten automáticamente.
- Workers (Celery): eventos en `worker_audit` y, para `check_expired_certificates`/`backup_database_to_minio`, también en `system_logs`.

### Formato de logs (para ingestion)

Por defecto texto con `rid=`. Para Loki/Grafana se recomienda JSON: `LOG_FORMAT=json` (ver `app/core/logging_config.py`).

### Loki + Grafana

Se provee un overlay **`certify-infra/docker-compose.loki.yml`** (Loki + Grafana sobre `proxy_network`) con:
- `certify-infra/loki/config.yaml` (single-binary, filesystem, retención 30d).
- `certify-infra/grafana/provisioning/datasources/loki.yaml` (datasource Loki + campo derivado `request_id`).
- `gateway/conf.d/grafana.conf` (Grafana tras authentik).

La ingestión se hace **desde la app**: si `LOKI_URL` está definida, `configure_logging()` añade un `LokiHandler` (cola + thread, `httpx`) que envía lotes con labels `source`/`level` y `request_id`.

```bash
# 1. Levantar Loki + Grafana junto a la infra
cd <ruta>/certify-infra
sudo docker compose -f docker-compose.yml -f docker-compose.loki.yml up -d

# 2. En el backend (prod), en el .env:
#    LOG_FORMAT=json
#    LOKI_URL=http://infra_loki:3100
#    LOG_SOURCE=api            # api | worker

# 3. Copiar gateway/conf.d/grafana.conf -> /etc/nginx/conf.d/ + certificado del subdominio
# 4. Redeployar el backend (api / celery-*)
```

## Personalización de la plataforma (/configuration)

El panel `/configuration` (solo **superuser**) personaliza, por tenant, sobre `platform_settings` (+ `email_templates`):

- **Organización / marca**: nombre, mensaje del dashboard (placeholders `{{app_name}}`, `{{organization}}`), datos de contacto y logo (MinIO).
- **Correo saliente (SMTP)**: host, puerto, usuario, contraseña (Fernet), TLS, remitente; envío de prueba.
- **Plantillas de correo**: asunto + cuerpo HTML por tipo, con placeholders y logo inline (`cid:logo`).
- **Pagos**: `mercadopago_enabled`, `mercadopago_marketplace_user_id` (comisión/currency desde settings globales).
- **Plantilla de certificado**: PDF base personalizado + previsualización y restauración.

Endpoints en `GET/PUT /configuration/{organization,email,payments,email/templates,certificate-template}`.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

La suite usa **SQLite** (`tests/conftest.py` fija `DATABASE_URL=sqlite+aiosqlite:///./test_certify.db`, `AUTO_CREATE_TABLES=true`, MinIO deshabilitado). Cubre cifrado de secretos, plantillas, servicios de configuración, RBAC, multitenancy, pagos, ciclo de renovación, reportes y validación de evaluaciones (14 archivos de test).

> Nota: como la BD de tests es un archivo (`test_certify.db`), borra `test_certify.db*` si necesitas una corrida limpia.

## Documentación de la API

Con la aplicación en marcha:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Notas y limitaciones conocidas

- **Aislamiento multitenant a nivel de aplicación** (no RLS de PostgreSQL). Los contextos *unscoped* (panel de superadmin, workers, webhooks) omiten el filtro de tenant de forma intencional.
- El `action` de auditoría `renewal_started` no está en el enum `CertificateAuditAction`.
- La plantilla de correo `purchase_confirmation` existe por defecto pero no es personalizable por `/configuration` (el enum/constraint solo admite 3 tipos).
- `CHECK_EXPIRED_INTERVAL_HOURS` está definido pero el *beat* usa un crontab fijo.
- CORS `allow_methods` no incluye `PUT` (aunque `/configuration` usa PUT): revisar según el despliegue.
- No hay CSP configurada en el backend (el frontend define su propia CSP en `index.html`).
- `passlib[bcrypt]` figura como dependencia, pero el hashing usa `bcrypt` directamente.

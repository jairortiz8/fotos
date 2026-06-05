# Deployment — desplegar RunFoto en Railway desde cero

Esta guía es para levantar RunFoto en un proyecto **nuevo** de Railway (por
ejemplo, si alguien clona el repo o si hay que recrear todo). Si ya tenés el
proyecto andando y sólo querés deployar un cambio, mirá `docs/runbook.md` →
"Cómo deployar".

> **Por qué Railway**: corre el backend, Postgres, Redis y los workers de Celery
> en una sola plataforma, sin tener que administrar servidores. El plan inicial
> apunta a ~$20/mes (ver `CLAUDE.md` §1).

## Resumen de la arquitectura en Railway

Un proyecto de Railway con **5 servicios**:

| Servicio   | Qué es                         | Cómo se crea                          |
| ---------- | ------------------------------ | ------------------------------------- |
| `web`      | Django + gunicorn (el sitio)   | desde el repo (Dockerfile)            |
| `worker`   | Celery worker (tasks async)    | desde el repo (Dockerfile)            |
| `beat`     | Celery beat (crons)            | desde el repo (Dockerfile)            |
| `Postgres` | base de datos + pgvector       | plantilla de Railway (`+ New`)        |
| `Redis`    | cache + broker de Celery       | plantilla de Railway (`+ New`)        |

Los tres servicios de código (`web`, `worker`, `beat`) apuntan al **mismo repo**
y usan el **mismo `Dockerfile`**; cambian sólo en el "Start Command".

> **Estado actual (importante)**: en el Railway de Jair hoy **sólo corre `web` +
> `Postgres` + `Redis`**. Los servicios `worker` y `beat` están **pendientes de
> crear** — por eso, en prod, no corren las tasks async (OCR, caras, crons de
> retención, backup). Esta guía incluye cómo crearlos; es lo principal a destrabar
> para que el sistema funcione completo en producción.

## Paso 0 — Requisitos previos

- Cuenta en [Railway](https://railway.app).
- El repo en GitHub (Railway deploya desde un repo conectado).
- Una cuenta de Cloudflare R2 con un bucket y un token "Object Read & Write"
  (ver `docs/runbook.md` → "Setup inicial de Cloudflare R2"). Vas a necesitar:
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`.
- (Opcional) Un DSN de Sentry para tracking de errores.

## Paso 1 — Crear el proyecto y conectar el repo

1. En Railway: **New Project** → **Deploy from GitHub repo** → elegí el repo.
2. Railway detecta el `Dockerfile` y crea el primer servicio. Renombralo a
   **`web`** (Settings → Service Name).
3. Railway va a intentar buildear y arrancar; va a fallar hasta que pongas las
   variables de entorno (Paso 4) y aprovisiones la DB (Paso 2). Es esperable.

## Paso 2 — Aprovisionar Postgres (con pgvector)

1. Dentro del proyecto: **+ New** → **Database** → **Add PostgreSQL**.
   - Railway usa una imagen de Postgres con pgvector disponible. En prod corremos
     **Postgres 18** (`ghcr.io/railwayapp-templates/postgres-ssl:18`). En local
     se usa **Postgres 16**; las migraciones de Django son agnósticas a la versión
     mayor y pgvector ≥ 0.7 corre en ambas (ver `CLAUDE.md` §2).
2. Una vez creado, Railway expone la variable `DATABASE_URL` del servicio
   Postgres. La vas a referenciar desde `web`/`worker`/`beat` (Paso 4).
3. **Habilitar la extensión `vector`** (la usan los embeddings faciales). Conectate
   a la DB y corré:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

   Cómo correrlo: en el servicio Postgres de Railway hay una pestaña de
   **Data / Query** (o usá `psql` con la `DATABASE_URL` pública). Esto se hace
   **una sola vez**, antes del primer `migrate`.

## Paso 3 — Aprovisionar Redis

1. **+ New** → **Database** → **Add Redis**.
2. Railway expone la variable `REDIS_URL` del servicio Redis.
3. Redis se usa para tres cosas: cache de Django, broker de Celery y storage del
   rate limiting. En este proyecto se separan por número de base de datos:
   - `REDIS_URL` → cache + rate limiting (db 0)
   - `CELERY_BROKER_URL` → broker (db 1)
   - `CELERY_RESULT_BACKEND` → resultados (db 2)

   Si la `REDIS_URL` que da Railway termina en `/0`, podés derivar las otras dos
   cambiando el número final a `/1` y `/2` respectivamente.

## Paso 4 — Variables de entorno del servicio `web`

En el servicio `web` → **Variables**, configurá lo siguiente. Las marcadas como
**referencia** se enganchan a los servicios de DB/Redis con la sintaxis
`${{ Postgres.DATABASE_URL }}` / `${{ Redis.REDIS_URL }}` (Railway las resuelve
solo). Los placeholders `<...>` los completás vos.

### Obligatorias

| Variable                  | Valor                                                        |
| ------------------------- | ------------------------------------------------------------ |
| `DJANGO_SETTINGS_MODULE`  | `config.settings.prod`                                       |
| `SECRET_KEY`              | `<un secreto largo y aleatorio>` (ver abajo cómo generarlo)  |
| `DEBUG`                   | `False`                                                      |
| `ALLOWED_HOSTS`           | `<tu-dominio-de-railway>` (ej. `fotos-production-xxxx.up.railway.app`), separado por comas si hay varios |
| `CSRF_TRUSTED_ORIGINS`    | `https://<tu-dominio-de-railway>` (con esquema, separado por comas) |
| `DATABASE_URL`            | **referencia** → `${{ Postgres.DATABASE_URL }}`              |
| `REDIS_URL`               | **referencia** → `${{ Redis.REDIS_URL }}` (db 0)             |
| `CELERY_BROKER_URL`       | `${{ Redis.REDIS_URL }}` apuntando a db 1                    |
| `CELERY_RESULT_BACKEND`   | `${{ Redis.REDIS_URL }}` apuntando a db 2                    |
| `SITE_NAME`               | `RunFoto` (o el nombre final cuando se decida)               |
| `SITE_DOMAIN`             | `<tu-dominio-de-railway>`                                    |
| `R2_ACCESS_KEY_ID`        | `<de Cloudflare R2>`                                         |
| `R2_SECRET_ACCESS_KEY`    | `<de Cloudflare R2>`                                         |
| `R2_BUCKET_NAME`          | `runfoto-prod`                                               |
| `R2_ENDPOINT_URL`         | `https://<account-id>.r2.cloudflarestorage.com` (endpoint S3, no el europeo) |

Generá un `SECRET_KEY` con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### Recomendadas / opcionales

| Variable                     | Default                | Para qué                                  |
| ---------------------------- | ---------------------- | ----------------------------------------- |
| `SENTRY_DSN`                 | (vacío)                | tracking de errores (si está vacío, Sentry no se inicializa) |
| `SENTRY_ENVIRONMENT`         | `production`           | etiqueta de entorno en Sentry             |
| `SENTRY_TRACES_SAMPLE_RATE`  | `0.1` (en prod)        | muestreo de performance                   |
| `GIT_SHA`                    | `unknown`              | versión/release (se ve en `/healthz` y en Sentry) |
| `LOG_LEVEL`                  | `INFO`                 | nivel de logging                          |
| `FACE_SEARCH_ENABLED`        | `True` (default)       | **poné `False` en prod** mientras el web esté capado a 1 GB de RAM (el modelo facial necesita ~1.1 GB; ver troubleshooting). |
| `R2_PUBLIC_BASE_URL`         | (vacío)                | dominio público opcional para servir archivos sin firmar |
| `PHOTO_UPLOAD_MAX_MB`        | `15`                   | tamaño máximo de upload por foto          |
| `NOTIFIER_BACKEND`           | `whatsapp_manual`      | backend de notificaciones (hoy sólo WhatsApp manual) |
| `LANGUAGE_CODE`              | `es`                   | idioma                                    |
| `TIME_ZONE`                  | `America/Guatemala`    | zona horaria (afecta crons de Celery)     |

> **Nota sobre `FACE_SEARCH_ENABLED`**: en prod hoy va en `False` a propósito.
> La búsqueda por selfie corre síncrona en el proceso web (por privacidad) y
> cargar `buffalo_l` necesita ~1.1 GB; con el web capado a 1 GB, eso provocaba
> OOM (502 que tiraba el sitio). Para reactivarla, subí la RAM del servicio web a
> ≥2 GB y poné `FACE_SEARCH_ENABLED=True`. La búsqueda por dorsal (método
> principal) no depende de esto.

## Paso 5 — Comando de arranque del `web`

El `Dockerfile` ya trae un `CMD` por defecto para el web (migra y arranca
gunicorn). No hace falta override, pero por claridad este es el comando:

```bash
python manage.py migrate --noinput && \
gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} \
    --workers 1 --threads 4 --timeout 120 --access-logfile -
```

Detalles de por qué `--workers 1 --threads 4 --timeout 120`: la inferencia facial
corre en el proceso web y el modelo pesa >700 MB en RAM; con el web capado a 1 GB
se mantiene **una sola copia** del modelo (1 worker) compartida por 4 threads
(onnxruntime es thread-safe y libera el GIL). El `--timeout 120` da margen a la
primera búsqueda por selfie (carga el modelo). Si subís la RAM, podés subir
`--workers`.

## Paso 6 — Healthcheck

Ya está configurado en `railway.toml`:

```toml
[deploy]
healthcheckPath = "/healthz/lite"
healthcheckTimeout = 30
```

`/healthz/lite` chequea **sólo la DB** (barato, no depende de R2 ni de los
workers). Es el probe que usa Railway para decidir si el deploy está sano.

> Hay también un `/healthz` "profundo" (db + redis + r2 + workers + beat) para
> monitoreo manual, pero **no** se usa como probe de Railway: devolvería
> `degraded` si falta el worker, y eso tumbaría deploys sanos. Ver `docs/api.md`.

## Paso 7 — Crear los servicios `worker` y `beat`

Estos dos faltan en el Railway actual. Sin ellos, en prod no corren las tasks
async (procesamiento de uploads, crons de retención/cleanup, backup).

Para cada uno:

1. **+ New** → **GitHub Repo** → **el mismo repo** (Railway permite varios
   servicios desde un repo).
2. En **Settings** del servicio, override el **Start Command**:
   - `worker`:
     ```bash
     celery -A config worker --loglevel=info
     ```
   - `beat`:
     ```bash
     celery -A config beat --loglevel=info
     ```
3. **Copiar las mismas variables de entorno** que el `web` (todas: settings, DB,
   Redis, R2, etc.). Lo más práctico es referenciar Postgres/Redis igual que en
   el `web`. El `worker` necesita **≥1 GB de RAM** (carga modelos ML para el
   procesamiento de uploads).
4. El `worker` y el `beat` **no exponen puerto** ni necesitan healthcheck HTTP
   (no son servidores web). Desactivá el healthcheck si Railway lo pide.

Una vez corriendo, verificá con el `/healthz` profundo (debería mostrar
`celery_workers.workers >= 1`) o con `railway logs` del worker.

## Paso 8 — Dominio y primer deploy

1. Railway → servicio `web` → **Settings** → **Networking** → **Generate Domain**
   (o conectá un dominio propio cuando exista). Agregá ese dominio a
   `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`.
2. Dispará un deploy (push a `main` o **Deploy** manual). El `web` corre
   `migrate --noinput` al arrancar.
3. Cuando termine, abrí `https://<tu-dominio>/healthz/lite` → debería devolver
   `{"status":"ok"}`.

## Paso 9 — Crear el super admin

RunFoto tiene **una sola cuenta** (el super admin). Creala una vez:

```bash
# Con el Railway CLI, apuntando al servicio web:
railway service link web
railway run python manage.py createsuperuser
```

Después entrá a `https://<tu-dominio>/dashboard/login/` con esa cuenta.

> Password mínimo 12 caracteres (validadores fuertes de Django).

## Paso 10 — (Opcional) Data de prueba

```bash
railway run python manage.py seed_data --clean
```

Crea un superuser (te imprime la password), eventos en distintos estados, fotos
con dorsales sintéticos, links de fotógrafo y audit logs.

## Flujo de deploys posteriores

1. Mergeás un PR en `main`.
2. GitHub Actions corre `ruff` + `mypy` + `pytest` (tiene que estar verde).
3. Railway detecta el push y rebuildeas los servicios de código.
4. El `web` corre `migrate --noinput` antes de levantar gunicorn.

Rollback, restauración de backups y operación diaria: `docs/runbook.md`.
Problemas comunes durante el deploy: `docs/troubleshooting.md`.

## Diferencia de versiones de Postgres (local vs prod)

- **Local**: Postgres **16** (Homebrew o `pgvector/pgvector:pg16` en
  docker-compose), con pgvector 0.8.
- **Prod (Railway)**: Postgres **18**, con pgvector habilitado vía
  `CREATE EXTENSION vector`.

Las versiones están a propósito desparejas: las migraciones de Django son
agnósticas a la versión mayor y pgvector ≥ 0.7 corre en ambas. Migrar el local a
pg18 era posible pero no aportaba nada y rompía el flujo de instalación
documentado (ver `CLAUDE.md` §2). El único detalle a recordar es que el backup
secundario con `pg_dump` necesita un cliente ≥ versión del servidor: para
dumpear pg18 en prod hace falta `postgresql-client-18` en la imagen Docker, que
hoy **no está incluido** (ADR 0010). El backup primario lo cubren los snapshots
de Railway.

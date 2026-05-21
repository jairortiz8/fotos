# RunFoto

> Plataforma web **gratuita** de fotos de carreras deportivas para
> Centroamérica. Búsqueda por dorsal (OCR) o por selfie (reconocimiento
> facial). Sin cuenta, sin pago.

## Stack

- **Backend**: Django 5 + Python 3.12 (DRF para JSON puntual)
- **Frontend (SSR)**: HTMX + Alpine.js + Tailwind CSS v4
- **DB**: PostgreSQL 16 + pgvector
- **Async**: Celery + Redis
- **ML**: PaddleOCR + EasyOCR (dorsales) · InsightFace `buffalo_l` (caras)
- **Storage**: Cloudflare R2 (boto3, S3-compatible)
- **Hosting**: Railway
- **Monitoring**: Sentry (free tier)

Más detalle en [`docs/adr/0001-stack-selection.md`](docs/adr/0001-stack-selection.md).

## Cómo levantar el proyecto localmente

Requiere macOS o Linux con `brew` (o equivalente), y los siguientes
binarios disponibles antes de empezar:

```bash
# Una sola vez en tu máquina
brew install python@3.12 postgresql@16 pgvector redis

# pgvector que brew distribuye sólo trae el bottle para pg17/pg18.
# Para pg16 hay que compilar desde fuente:
git clone --depth 1 --branch v0.8.0 https://github.com/pgvector/pgvector.git /tmp/pgvector
cd /tmp/pgvector
PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config make
PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config make install
cd -

brew services start postgresql@16
brew services start redis
```

Después, dentro del repo:

```bash
# Crear DB y extensión vector
/opt/homebrew/opt/postgresql@16/bin/createuser -s runfoto || true
/opt/homebrew/opt/postgresql@16/bin/psql -d postgres \
    -c "ALTER USER runfoto WITH PASSWORD 'runfoto';"
/opt/homebrew/opt/postgresql@16/bin/createdb -O runfoto runfoto || true
/opt/homebrew/opt/postgresql@16/bin/psql -d runfoto \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Variables de entorno
cp .env.example .env
# Generá un SECRET_KEY real:
python3.12 -c "import secrets; print(secrets.token_urlsafe(50))"
# Pegalo en .env como SECRET_KEY=...

# Venv + deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Migrations
python manage.py migrate

# Tailwind (una sola vez para instalar deps de Node):
python manage.py tailwind install
python manage.py tailwind build

# Levantar el server
python manage.py runserver
```

Abrí http://localhost:8000/ → debería ver la landing temporal.
Health check: http://localhost:8000/healthz → `{"status":"ok",...}`

### Alternativa: Docker Compose

Si tenés Docker Desktop instalado:

```bash
docker compose up
```

Levanta `db` (pgvector/pgvector:pg16), `redis`, `web` (Django con autoreload),
`worker` y `beat` (Celery). El primer build tarda unos minutos.

## Cómo correr los tests + linter

```bash
# Tests
pytest -v

# Linter + formateador + types (lo que corre CI también)
ruff check .
ruff format --check .
black --check .
mypy .
```

Pre-commit hooks (ejecutan ruff + black + mypy en cada commit local):

```bash
pre-commit install
```

## Cómo deployar

Hoy todavía no está conectado Railway al repo. Cuando se conecte:

1. Mergeás PR en `main`.
2. GitHub Actions corre lint + tests (verde antes de mergear).
3. Railway detecta el push, builda con el `Dockerfile` multi-stage
   y deploya 3 servicios: `web` (gunicorn), `worker` (celery worker),
   `beat` (celery beat).
4. Postgres + Redis se aprovisionan desde el dashboard de Railway,
   no desde código.

Más detalle en [`docs/runbook.md`](docs/runbook.md).

## Modelos principales (Fase 1)

| Modelo                                 | Para qué sirve                                                                                                              |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `apps.core.User` (AbstractUser)        | Super admin (hoy uno solo). Custom desde el día 1 para evitar migrations dolorosas después.                                 |
| `apps.core.UserMFA`                    | Stub de TOTP (campo `totp_secret` encriptado, NULL hasta activar). `EncryptedCharField` custom via Fernet.                 |
| `apps.core.AuditLog`                   | Append-only. Acciones del admin (event.created, photo.approved, …). IP anonimizada.                                         |
| `apps.events.Event`                    | Evento de carrera. 8 estados + 3 visibilidades + 4 campos de retención (`public_until`, `searchable_until`, `archive_until`, `permanent_archive`). |
| `apps.photographers.PhotographerLink`  | Token URL único por fotógrafo. `token_hash` (sha256), no se guarda el plano. Métodos `verify_token()`, `is_valid()`, `revoke()`. |
| `apps.photos.Photo`                    | Una foto. R2 keys (`original_key` único, `preview_key`, `thumbnail_key`), EXIF detallado, status, flags ML.                |
| `apps.photos.Bib`                      | Dorsal detectado/reportado en una foto. Source (OCR/manual), confidence, bbox. Unique `(photo, number, source)`.            |
| `apps.photos.FaceEmbedding`            | Vector 512-d (pgvector + HNSW índice coseno). Edad estimada → `is_minor` (activa blur en preview).                          |
| `apps.privacy.DataDeletionRequest`     | Log de borrados solicitados por usuarios (`/privacy/delete-my-data`). IP hasheada, sin embedding persistente.               |

ER completo en [`docs/erd.md`](docs/erd.md) (Mermaid).

Política de retención escalonada de eventos: ver [`docs/adr/0003-retention-policy.md`](docs/adr/0003-retention-policy.md).
Elección de paquete admin: ver [`docs/adr/0002-admin-interface.md`](docs/adr/0002-admin-interface.md).

### Sembrar data de prueba

```bash
python manage.py seed_data --clean
```

Crea 1 superuser (te imprime la password), 3 eventos en distintos estados, 50 fotos
por evento con dorsales sintéticos, links de fotógrafo, y audit logs históricos.
Después entrá a http://127.0.0.1:8000/admin/ para verlo.

## Para fotógrafos: cómo funciona el portal (Fase 2)

El admin (`runfoto-admin`) genera un link único para cada fotógrafo:

```bash
python manage.py shell
```

```python
from apps.events.models import Event
from apps.photographers.models import PhotographerLink

event = Event.objects.get(slug="maraton-antigua-2026")
link, raw_token = PhotographerLink.generate_token_and_create(
    event,
    name="Lucia Pérez",
    email="lucia@ejemplo.com",
    photo_limit=300,        # opcional
    expires_in_days=45,     # opcional; default 30 después del evento
)
print(f"https://<dominio>/u/{raw_token}/")
```

El admin **copia esa URL una sola vez** y se la manda al fotógrafo por WhatsApp
(o como prefiera). El token plano no queda guardado en DB — solo el `sha256`.

El fotógrafo abre el link en su browser (cualquiera, sin cuenta) y ve el portal
de subida. Drag-and-drop JPGs, máximo 15 MB cada uno, sin límite de cantidad
(salvo que se le ponga `photo_limit`). Por cada foto:

1. El backend valida que es JPEG real (magic bytes).
2. La sube a Cloudflare R2 (`events/<slug>/originals/<uuid>.jpg`).
3. Crea el registro `Photo` en `status='processing'`.
4. Dispara una task Celery (`process_photo`) que:
   - Extrae EXIF + dimensiones.
   - Genera preview con watermark diagonal (1200px, WebP).
   - Genera thumbnail (400px, WebP).
   - Encadena `run_ocr_on_photo` (PaddleOCR + EasyOCR fallback).
5. El status pasa a `pending_review`. El admin lo aprueba desde `/admin/`.

**Rate limits**: 60 req/min al portal por IP, 100 fotos/min al endpoint de
upload por token (anti-flood pero permite ráfagas).

**Revocar un link**: ver [`docs/runbook.md`](docs/runbook.md#cómo-crear-un-link-de-upload-de-fotógrafo-manual-fase-2).

## Estructura de carpetas

```
runfoto/
├── manage.py                 # entrada CLI Django
├── pyproject.toml            # deps + config ruff/black/mypy/pytest
├── Dockerfile                # multi-stage (Tailwind + Python + runtime)
├── docker-compose.yml        # stack local (db + redis + web + workers)
├── railway.toml              # config compartida del build en Railway
├── .pre-commit-config.yaml   # hooks (ruff + black + mypy)
├── .github/workflows/ci.yml  # CI: lint + types + tests
│
├── config/                   # Django project
│   ├── __init__.py           # importa Celery
│   ├── celery.py
│   ├── urls.py
│   ├── wsgi.py
│   ├── asgi.py
│   └── settings/
│       ├── base.py           # comunes a dev y prod
│       ├── dev.py            # debug toolbar, autoreload
│       └── prod.py           # security headers, Sentry, WhiteNoise
│
├── apps/                     # apps de negocio
│   ├── core/                 # health, landing, utils, context_processor
│   ├── events/               # modelo Event + admin
│   ├── photos/               # Photo, Bib, FaceEmbedding
│   ├── photographers/        # PhotographerLink (token)
│   ├── search/               # búsqueda por dorsal y por selfie
│   ├── downloads/            # generación de ZIPs
│   ├── ml/                   # OCR + face recognition pipelines
│   ├── notifications/        # Notifier abstracto (WhatsApp manual hoy)
│   ├── privacy/              # delete-my-data, retention crons
│   └── dashboard/            # custom admin (no Django admin)
│
├── theme/                    # django-tailwind app
│   ├── apps.py
│   ├── static_src/           # source CSS + package.json (Tailwind v4)
│   └── static/css/dist/      # styles.css compilado (gitignored)
│
├── static/                   # archivos estáticos del proyecto
│   ├── fonts/                # .woff2 auto-hospedados
│   ├── css/                  # extra (no Tailwind)
│   └── js/                   # HTMX + Alpine + custom
│
├── templates/                # templates Django globales
│   ├── base.html
│   ├── public/               # landing + galerías + búsqueda
│   ├── photographer/         # portal de upload
│   ├── dashboard/            # admin custom
│   └── _partials/            # HTMX fragments + wordmark, etc.
│
├── locale/                   # .po files (es activo, en placeholder)
│
├── tests/                    # pytest
│   ├── conftest.py
│   ├── factories.py          # vacío en Fase 0
│   └── test_*.py
│
├── docs/
│   ├── adr/                  # Architecture Decision Records
│   └── runbook.md            # operaciones (deploy, rollback, etc.)
│
└── reference/
    └── runfoto-design/       # zip de Claude Design (referencia visual)
```

## Estado actual

**Fase 0 — Setup** completada.

Fase 1 (modelos + admin) arranca cuando se dé OK explícito.

## Licencia

Proprietary. Todos los derechos reservados.

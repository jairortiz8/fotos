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

## Troubleshooting común

| Síntoma | Causa probable / Solución |
|---|---|
| Búsqueda por selfie da 503 en prod | Es a propósito: `FACE_SEARCH_ENABLED=false` (el modelo no entra en 1 GB). Subir RAM del servicio web → ver runbook. |
| Tests fallan con `relation ... does not exist` | La DB local no está migrada: `python manage.py migrate`. |
| `cv2`/`libGL.so.1` al importar en local | Faltan libs del sistema; en mac: `brew install`. En Docker ya están (ver Dockerfile). |
| Las fotos suben pero quedan en `processing` | El `worker` de Celery no está corriendo (en prod sigue pendiente de crear). |
| Los crons de retención no corren | El `beat` de Celery no está corriendo (pendiente en prod). |
| CSP rompe algo en el browser | Revisar `CONTENT_SECURITY_POLICY` en `config/settings/base.py` y la consola del navegador. |
| El backup `pg_dump` falla en prod | Falta `postgresql-client-18` en la imagen (ver ADR 0010); usar snapshots de Railway. |

Más incidentes y cómo resolverlos en [`docs/runbook.md`](docs/runbook.md) → Incidentes.

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

## Privacidad y reconocimiento facial (Fase 4)

RunFoto usa reconocimiento facial (InsightFace `buffalo_l`) para que los
corredores se encuentren por selfie. El manejo de datos biométricos es
estricto — documento completo en [`docs/privacy.md`](docs/privacy.md):

- **El selfie del usuario nunca se guarda** (ni archivo ni embedding). La
  búsqueda y el borrado son síncronos: el embedding vive en RAM durante el
  request y se descarta. Nunca toca Celery/Redis.
- **Embeddings de las fotos**: se guardan en Postgres (pgvector) y se borran a
  los **90 días** desde el último uso (cron diario).
- **Menores**: caras estimadas <16 se difuminan automáticamente en el preview
  (el original queda intacto); caras <22 se marcan para revisión del admin.
- **Borrá tus datos**: `/privacidad/borrar-mis-datos/` — subís un selfie y se
  borran todas tus fotos y embeddings de todos los eventos.

Búsqueda por selfie: `/eventos/<slug>/buscar-selfie/`.
Umbrales y decisiones: [`docs/adr/0006`](docs/adr/0006-face-recognition-threshold.md) (similitud) · [`docs/adr/0007`](docs/adr/0007-pgvector-index-type.md) (índice HNSW).

## Para corredores: cómo buscar tus fotos (Fase 3)

1. Entrá a la home (`/`). Vas a ver los eventos públicos.
2. Hacé click en tu evento, o escribí tu número de dorsal directo en el
   buscador del home.
3. En la galería del evento (`/eventos/<slug>/`):
   - **Buscá por dorsal**: escribí tu número (ej. `1042`) y dale "Buscar".
     Filtra a las fotos donde el OCR detectó ese dorsal.
   - Si no aparece nada, te sugerimos dorsales con **lectura OCR similar**
     que sí existen en el evento (ej. buscás `8999` y te ofrece `9999`).
4. Click en una foto → se abre el **lightbox** con el preview (marca de agua).
   Navegá con las flechas o `←`/`→`, cerrá con `Esc`.
5. **Seleccioná** varias fotos (checkbox arriba a la derecha de cada una) y
   tocá "Descargar" → se arma un **ZIP en alta resolución sin marca de agua**.
   El link de descarga vive 1 hora.

Estados de un evento (política de retención, ver ADR 0003):
- **Live / próximo**: galería completa + búsqueda + descargas.
- **Cerrado** (91-180 días): galería oculta, **solo búsqueda por dorsal**.
- **Archivado** (181-365 días): página pública devuelve 404 amigable.

Rate limiting (ver ADR 0005): 60 búsquedas/hora por IP, 10/día por dorsal,
5 ZIPs/hora por IP.

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

## Para administradores: usando el dashboard (Fase 5)

El super admin gestiona todo desde un **dashboard custom** en `/dashboard/`
(no el Django admin, que queda como fallback en `/admin/django/`).

- **Login**: `/dashboard/login/` con la cuenta super admin. Sesión de 12 horas.
- **Crear eventos** y **generar links de upload** (con QR + mensaje de WhatsApp
  listo para copiar y mandar al fotógrafo).
- **Cola de aprobación**: grilla con multi-select, acciones en bloque y atajos
  de teclado (`A` aprobar, `R` rechazar, `←/→` navegar, `Enter` detalle). En el
  detalle se editan los dorsales detectados a mano.
- **Audit log**: registro de solo lectura de todas las acciones admin.
- **Estadísticas**: fotos por día/hora y totales por evento (sin tracking de
  búsquedas individuales, por privacidad).

El paso a paso operativo está en [`docs/runbook.md`](docs/runbook.md) →
"Usar el dashboard admin".

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

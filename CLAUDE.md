# CLAUDE.md — RunFoto

> Este archivo es el contexto persistente del proyecto. Claude Code lo lee al inicio de cada sesión.
> Si encontrás algo desactualizado o contradictorio, **pará y preguntá antes de avanzar**.

---

## 1. Qué es RunFoto

Plataforma web **gratuita** de fotos de carreras deportivas para el mercado centroamericano (**El Salvador** inicial, con Guatemala y la región como expansión). Permite a corredores buscar y descargar fotos suyas de eventos de running, trail, ultra, ciclismo y similares — usando **dos métodos de búsqueda**:

1. **Por número de dorsal** (OCR automático en upload + corrección manual del admin)
2. **Por selfie** (reconocimiento facial con embeddings y similitud vectorial)

Las fotos son **100% gratuitas** para los corredores. No hay e-commerce, no hay cart, no hay pricing, no hay cuentas para corredores ni fotógrafos. **Solo hay UNA cuenta de super admin** (el dueño del producto, Jair).

### Modelo de operación

- **Corredores**: visitan el sitio sin cuenta, buscan fotos por dorsal o selfie, descargan ZIP en alta resolución sin marca de agua.
- **Fotógrafos**: no tienen cuenta. Acceden a un **portal de upload via token URL único** (`/u/{token}`) generado por el admin. Drag-and-drop sus fotos. Su token expira en X días.
- **Super admin (Jair)**: única cuenta del sistema. Crea eventos, genera links de upload, aprueba fotos antes de publicarlas, gestiona dorsales detectados, ve estadísticas, borra datos a pedido de usuarios.

### Escala objetivo (año 1)

- 15-20 eventos al año
- Máximo 4,000 fotos por evento
- JPGs de 3-5 MB (alta resolución original)
- Test inicial: 300 fotos en un solo evento
- Budget total: ~$20/mes inicialmente

---

## 2. Decisiones de stack (NO renegociar sin preguntarme primero)

### Backend
- **Django 5** + **Python 3.12**
- **Django REST Framework** solo donde haga falta API JSON (mayoría es SSR con HTMX)
- **PostgreSQL** + **pgvector** extension (para embeddings faciales)
  - Dev local: **Postgres 16** (Homebrew, con pgvector 0.8 compilado para pg16)
  - Producción Railway: **Postgres 18** (imagen `ghcr.io/railwayapp-templates/postgres-ssl:18`, con pgvector habilitado vía `CREATE EXTENSION vector`)
  - Decisión: dejamos las versiones desparejadas. Las migrations de Django son agnósticas a la versión mayor y pgvector ≥0.7 corre en ambas. Migrar local a pg18 era posible pero no aportaba nada y rompía el flujo de instalación documentado.
- **Celery** + **Redis** para tasks async (OCR, face recognition, ZIP generation, cleanup)
- **Pillow** para procesamiento de imágenes

### Frontend (dentro del proyecto Django, SSR)
- **HTMX** para interactividad sin SPA
- **Alpine.js** para estado de UI local (toggles, modales, multi-select)
- **Tailwind CSS** (vía django-tailwind o build con esbuild — Claude Code decide cuál es más simple)
- **Templates Django** + `{% trans %}` para i18n

### ML/Visión
- **PaddleOCR** (primario) + **EasyOCR** (fallback) para detección de dorsales
- **InsightFace** (modelo `buffalo_l`) para embeddings faciales — vectores de 512 dimensiones
- Procesamiento async en Celery workers, **nunca bloqueante** en el request

### Storage & deploy
- **Cloudflare R2** para fotos originales, previews con watermark, thumbnails, y ZIPs generados
- Cliente: **boto3** con endpoint custom (R2 es S3-compatible)
- **Railway** para hosting (backend + Postgres + Redis + workers en una sola plataforma)
- Variables de entorno via Railway secrets, **nunca** en código

### Email / Notificaciones
- **Por ahora: nada de email**. Los links de upload se copian del admin y se mandan por WhatsApp manualmente.
- **Pero la arquitectura debe estar lista**: módulo `notifications/` con interface abstracta `Notifier`. Hoy implementa `WhatsAppManualNotifier` (que solo muestra el link al admin para copiar). Mañana se enchufa `BrevoNotifier` o `ResendNotifier` cambiando una env var.

### Monitoring
- **Sentry** (free tier, 5k errors/mes) para tracking de errores en producción
- Sin analytics por ahora; preparado para agregar Plausible/Umami self-hosted después

### Idiomas
- **Español es el único idioma activo**, usando **"vos"** rioplatense/latinoamericano (no "tú")
- **Pero todos los strings de UI deben estar envueltos en `{% trans %}` o `gettext()`** — i18n estructurado desde el día 1
- Locales preparados: `es` (activo), `en` (placeholder vacío)

### Dominio
- **Sin dominio comprado todavía**. El nombre "RunFoto" puede cambiar.
- Usar variables de entorno `SITE_NAME` (default: "RunFoto") y `SITE_DOMAIN` (default: dominio de Railway en dev/staging)
- **Toda referencia al nombre debe ir por `{{ site_name }}` en templates** — nunca hardcodear "RunFoto"

---

## 3. Principios de código no-negociables

### Seguridad
- **Nunca** exponer fotos originales públicamente. Acceso solo vía URLs firmadas con expiración (15 min).
- **Nunca** loggear PII (emails, embeddings, dorsales con nombre).
- **Siempre** usar Django ORM (nunca raw SQL para inputs de usuario).
- **CSRF** activado en todos los forms.
- **HTTPS only** en producción, redirect HTTP→HTTPS.
- **HSTS** headers activados.
- **Content Security Policy** restrictiva.
- **Django Defender** o equivalente: rate limit estricto en `/admin/login` (5 intentos / 15 min).
- **Sesiones admin**: 12 horas máximo, sin "remember me" largo, cookies `Secure` + `HttpOnly` + `SameSite=Strict`.
- **Password admin**: mínimo 12 caracteres, validadores fuertes de Django.
- **2FA**: NO activado todavía, pero **dejar tabla `UserMFA` creada con columna `totp_secret` nullable** y views stub para activar después sin migración estructural.

### Privacidad (crítico — reconocimiento facial)
- **Retención de embeddings faciales**: **90 días** desde el último match. Cron job diario (Celery beat) que borra embeddings inactivos.
- **Política de retención escalonada de EVENTOS** (independiente de los embeddings):

  | Tiempo desde la fecha del evento | Estado          | Qué pasa                                                                                                                                  |
  | -------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
  | 0–90 días                        | `live` → `public_closed` | Galería pública activa, búsquedas activas, descargas habilitadas.                                                                |
  | 91–180 días                      | `searchable_only` | Galería pública cerrada. Solo búsquedas por dorsal/selfie. Mensaje claro al corredor: "Para ver fotos, buscá por dorsal o subí selfie." |
  | 181–365 días                     | `archived`      | Solo admin puede ver/buscar. Páginas públicas devuelven 404 amigable con info de contacto.                                                |
  | 366+ días                        | `pending_deletion` → `deleted` | Cron borra fotos de R2 (originals + previews + thumbs). Queda solo metadata del evento en DB para referencia histórica.    |

  Plazos configurables por evento (`public_until`, `searchable_until`, `archive_until` en el modelo `Event`).
  Bandera `permanent_archive=True` en el evento ignora estas reglas (caso de organizador que pague por archivo permanente).

- **Endpoint `/privacy/delete-my-data`**: público, sin login. El usuario sube su selfie, el sistema encuentra y borra TODAS sus fotos y embeddings de TODOS los eventos. Logged y confirmado.
- **Banner de privacidad** obligatorio en homepage y en pantalla de búsqueda por selfie, explicando qué datos se procesan.
- **Las fotos de menores son automáticamente blureadas en el preview público** — el sistema detecta caras < cierta edad (InsightFace tiene esto) y aplica blur en el preview con watermark. El original se mantiene intacto para el admin.
- **No usar los embeddings para nada que no sea el matching directo** — no analytics, no entrenamiento, nada.

### Rate limiting
- **Búsqueda por dorsal**: 60 búsquedas/hora por IP
- **Búsqueda del mismo dorsal por IP**: máximo 10 por día (capa anti-scraping)
- **Búsqueda por selfie**: 20 búsquedas/hora por IP (más caro computacionalmente)
- **Upload de fotos (fotógrafo)**: 100 fotos por minuto por token (anti-flood)
- **Descarga de ZIP**: 5 ZIPs por hora por IP (los ZIPs son caros de generar)
- Usar **django-ratelimit** o equivalente. Storage: Redis.

### Tokens de fotógrafo
- Token = string de 32 caracteres URL-safe (`secrets.token_urlsafe(24)`)
- **NUNCA** guardado en plano en la DB. Guardar `sha256(token)` y comparar hashes.
- Vida útil configurable por evento, default 30 días después del evento.
- Revocable manualmente desde admin (toggle `is_active = False`).
- Si se intenta usar un token expirado/revocado, mostrar mensaje claro: "Este link ya no es válido. Contactá al admin."

### Performance
- **Previews**: máximo 1200px lado largo, WebP, calidad 80, con marca de agua diagonal.
- **Thumbnails**: 400px lado largo, WebP, calidad 75.
- **Originales**: tal como subidos, en bucket privado, accesibles solo vía URL firmada al momento de descarga.
- **Cache de búsquedas**: las búsquedas por dorsal se cachean en Redis 5 minutos.
- **Pagination**: galerías de fotos paginadas a 60 fotos por página (HTMX infinite scroll).
- **DB queries**: usar `select_related` y `prefetch_related` agresivamente. **Cero N+1**.
- **Django Debug Toolbar** en dev para detectar queries problemáticas.
- **Connection pooling** con PgBouncer en producción si Railway lo permite, sino conexiones persistentes.

### Testing
- **Tests desde el día 1**, escritos junto con cada feature.
- **Framework**: `pytest` + `pytest-django` + `factory-boy` para fixtures.
- **Coverage mínimo**: 80% en modelos, views críticas, OCR pipeline, face matching, autenticación de tokens, rate limiting.
- **Tests obligatorios para**:
  - Cada modelo (validaciones, métodos custom)
  - Cada vista pública (status codes, contexto, permisos)
  - Cada endpoint protegido (sin auth → 401/403)
  - Pipeline OCR (con foto sintética conocida)
  - Pipeline face matching (umbral de similitud, embeddings)
  - Generación y validación de tokens de fotógrafo
  - Rate limiting (que efectivamente bloquee tras N requests)
- **NO tests requeridos para**: templates HTML puros sin lógica, CSS, JS de presentación.
- Correr tests en CI antes de cada merge.

### Calidad de código
- **Linter**: `ruff` (reemplazo moderno de flake8 + isort + más)
- **Formatter**: `black`
- **Type checking**: `mypy` con `django-stubs`, modo estricto en código de negocio (servicios, modelos, tasks Celery). Modo permisivo en views/templates.
- **Pre-commit hooks** configurados con `pre-commit` (ruff + black + mypy en archivos modificados)
- **CI/CD**: GitHub Actions corriendo lint + tests + mypy en cada PR
- **Commits**: estilo Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, etc.)

---

## 4. Arquitectura general

### Estructura de carpetas (propuesta)

```
runfoto/
├── manage.py
├── pyproject.toml              # ruff, black, mypy, pytest config
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       └── ci.yml
├── docker-compose.yml          # postgres + redis local
├── Dockerfile
├── railway.toml
├── README.md
├── CLAUDE.md                   # este archivo
├── docs/
│   ├── adr/                    # Architecture Decision Records
│   └── runbook.md              # operaciones (cómo recuperar, cómo deployar)
├── config/                     # settings, urls, wsgi, celery
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── wsgi.py
│   ├── asgi.py
│   └── celery.py
├── apps/
│   ├── core/                   # base models, utilities, middleware
│   ├── events/                 # Event model + admin views
│   ├── photos/                 # Photo, Bib, FaceEmbedding models + storage
│   ├── photographers/          # PhotographerLink (token-based access)
│   ├── search/                 # search views (bib, selfie), rate limiting
│   ├── downloads/              # ZIP generation, download tracking
│   ├── ml/                     # OCR pipeline, face recognition pipeline
│   ├── notifications/          # abstract Notifier + WhatsAppManualNotifier
│   ├── privacy/                # delete-my-data flow, retention cron
│   └── dashboard/              # admin dashboard custom (no Django admin)
├── templates/
│   ├── base.html
│   ├── public/
│   ├── photographer/
│   ├── dashboard/
│   └── partials/               # HTMX partials
├── static/
│   ├── css/                    # Tailwind output
│   ├── js/                     # HTMX + Alpine + custom
│   └── img/                    # logos, placeholders
├── locale/
│   ├── es/LC_MESSAGES/
│   └── en/LC_MESSAGES/
├── tests/
│   ├── conftest.py
│   ├── factories.py
│   └── (mirror apps/ structure)
└── reference/
    └── runfoto-design/         # zip de Claude Design extraído (referencia visual)
```

### Modelos principales (orientativos — Claude Code los refina)

```python
# events/models.py
class Event:
    name: str
    slug: str (unique)
    date: date
    location: str
    description: text
    cover_image: ImageField
    # 8 estados, alineados con la política de retención de §3:
    status: choices(draft, upcoming, live, public_closed,
                    searchable_only, archived,
                    pending_deletion, deleted)
    visibility: choices(public, unlisted, private)
    public_until: datetime         # default: date + 90 días
    searchable_until: datetime     # default: date + 180 días
    archive_until: datetime        # default: date + 365 días
    permanent_archive: bool        # si True, ignora todas las fechas anteriores
    # Counters denormalizados (actualizados por signals/tasks):
    photo_count, pending_count, photographer_count,
    search_count, download_count: int
    created_at, updated_at

# photos/models.py
class Photo:
    event: FK Event
    photographer: FK PhotographerLink (nullable for admin uploads)
    original_key: str  # R2 key del original
    preview_key: str   # R2 key del preview con watermark
    thumbnail_key: str # R2 key del thumb
    capture_time: datetime (extracted from EXIF)
    exif_data: JSONField
    status: choices(pending_review, approved, rejected, deleted)
    width, height, file_size
    created_at

class Bib:
    photo: FK Photo
    number: str  # string porque pueden ser "A123"
    confidence: float (0-1)
    source: choices(ocr_paddle, ocr_easy, manual_admin, manual_user_report)
    bbox: JSONField  # bounding box {x, y, w, h}

class FaceEmbedding:
    photo: FK Photo
    embedding: VectorField(512)  # pgvector
    bbox: JSONField
    is_minor: bool  # InsightFace age estimate
    last_matched_at: datetime  # for retention cleanup
    created_at

# photographers/models.py
class PhotographerLink:
    event: FK Event
    photographer_name: str
    photographer_email: str (nullable, for future use)
    token_hash: str (sha256)
    expires_at: datetime
    is_active: bool
    photo_limit: int (nullable)
    photos_uploaded: int  # counter
    created_at, last_used_at

# core/models.py
class User(AbstractUser):
    # User custom desde el día 1 (cambiar después es doloroso).
    # AbstractUser ya trae username/password/email/etc.;
    # acá vendrán las extensiones que necesitemos sin migración estructural.
    pass  # TimeStampedModel mixin agrega created_at/updated_at

class UserMFA:
    user: OneToOneField(User)
    totp_secret: EncryptedCharField (nullable hasta activar)
    backup_codes: JSONField (list de hashes)
    is_active: bool
    activated_at: datetime (nullable)

class AuditLog:
    user: FK User (nullable, for anonymous events)
    action: str  # 'photo.approved', 'event.created', 'data.deleted',
                 # 'photographer_link.generated', 'photographer_link.revoked', ...
    target_type: str
    target_id: str
    metadata: JSONField
    ip_address: str (anonymized — IPv4 último octeto = 0)
    created_at

# privacy/models.py
class DataDeletionRequest:
    selfie_embedding_temp: VectorField  # solo durante el proceso
    matched_photos_count: int
    deleted_photos_count: int
    confirmed: bool
    requested_at, completed_at
```

---

## 5. Referencia visual

En la carpeta `reference/runfoto-design/` está el zip de Claude Design extraído. Contiene componentes React (`shared.jsx`, `public-screens.jsx`, `photographer-screen.jsx`, `admin-screens.jsx`) que **NO se usan directamente** — son la referencia visual de cómo deben verse las pantallas.

**Cuando construyas templates HTML+Tailwind, replicá**:

- **Paleta de colores exacta** (definida en `:root` de `index.html`):
  - `--bg: #0A0A0B`
  - `--surface: #17171A`
  - `--surface-2: #1F1F23`
  - `--border: #2A2A2E`
  - `--text-1: #FAFAFA`
  - `--text-2: #A1A1A6`
  - `--text-3: #6B6B70`
  - `--orange: #FC5200` (acción primaria — solo CTAs)
  - `--cyan: #00D4FF` (data — dorsales, métricas, timestamps)
  - `--green: #10B981`, `--amber: #F59E0B`, `--red: #EF4444`

- **Tipografía**:
  - Display/headings: **Space Grotesk** (700, 800, 900)
  - Body/UI: **Inter** (400, 500, 600)
  - Números/data/dorsales/timestamps/file sizes: **JetBrains Mono** (500, 600) — obligatorio

- **Componentes a replicar** (ver `shared.jsx`):
  - `Wordmark` — logo "RunFoto" con cuadradito naranja después de la última "o"
  - `Pill` — badges con tono (cyan, amber, green, neutral)
  - `StatCard` — tarjetas de métricas en dashboard
  - `CTA` y `Ghost` — botones primario y secundario
  - `PhotoPH` — placeholder para fotos (en producción son <img> reales)

- **Radios**: hero 24px, cards 12px, buttons/inputs 8px, bib badges 6px, photo gallery items 0px (contact-sheet feel) con 2px gap

- **Sin drop shadows** — depth via tonal layering y 1px borders

- **Modo claro** preparado pero default es modo oscuro

### Pantallas a implementar (del zip)

1. Landing público (mobile + desktop)
2. Galería del evento — búsqueda por dorsal ★ pantalla principal
3. Galería del evento — búsqueda por selfie
4. Empty state (no resultados)
5. Lightbox de foto con watermark visible
6. Bottom sheet de selección + descarga
7. Portal del fotógrafo (token URL, sin sidebar, sin cuenta)
8. Dashboard admin con sidebar
9. Modal de generar link de upload con QR
10. Cola de aprobación
11. Detalle de aprobación (drawer con EXIF + bibs detectados)
12. Galería en modo claro (variante)

---

## 6. Construcción por fases

**Importante**: este proyecto se construye en fases. **Al final de cada fase parás, comitteás todo, hacés deploy si aplica, y esperás mi OK antes de avanzar.**

### Fase 0 — Setup (esta es la primera tarea)
- Estructura del proyecto Django con `apps/`, settings divididos (base/dev/prod)
- `pyproject.toml` con ruff, black, mypy, pytest
- Pre-commit hooks
- GitHub Actions con CI básico (lint + tests)
- `docker-compose.yml` para Postgres + Redis local
- Railway config (`railway.toml`)
- Deploy inicial a Railway con health check `/healthz`
- README con instrucciones de setup local
- Primer commit + push

### Fase 1 — Modelos + Admin
- Crear todos los modelos enumerados arriba (Event, Photo, Bib, FaceEmbedding, PhotographerLink, AuditLog, DataDeletionRequest, UserMFA stub)
- Migrations
- Django Admin custom y bonito para super admin (no el default feo)
- Factories y fixtures para tests
- Tests de modelos (validaciones, métodos)
- Comando management para crear data de prueba (seed)

### Fase 2 — Upload fotógrafo + OCR
- Vista pública `/u/{token}` (validación de token, expiración, rate limit)
- Drag-and-drop upload con HTMX
- Almacenamiento en R2
- Generación de preview con watermark + thumbnail (Celery task)
- Pipeline OCR (Celery task): PaddleOCR primario + EasyOCR fallback
- Audit logging
- Tests del flujo completo

### Fase 3 — Galería pública + búsqueda por dorsal
- Landing público con eventos
- Vista de evento con galería paginada
- Búsqueda por dorsal con rate limiting
- Lightbox con preview watermarked
- Multi-select + descarga ZIP (Celery task)
- Empty state con sugerencias OCR
- Tests

### Fase 4 — Búsqueda por selfie + face recognition
- Pipeline face recognition en upload (extraer embeddings con InsightFace)
- Almacenar embeddings en pgvector
- Detección de menores → blur en preview
- Vista de búsqueda por selfie
- Matching por similitud coseno (umbral configurable)
- Banner de privacidad
- Tests

### Fase 5 — Admin dashboard + cola de aprobación
- Custom dashboard (no Django admin) con sidebar
- Stats cards
- Cola de aprobación con bulk actions
- Drawer de detalle de foto (EXIF, bibs editables)
- Generar link de upload con QR code
- Vista de evento (gestión completa)
- Tests

### Fase 6 — Privacidad + retención + polish
- Endpoint `/privacy/delete-my-data` (selfie → match → borrar)
- Cron job Celery beat: borrar embeddings inactivos > 90 días
- Cron job: borrar links de fotógrafo expirados
- HSTS, CSP, headers de seguridad
- Sentry integrado
- Página de privacidad / términos
- Tests

### Fase 7 — i18n + accessibility + final
- Todos los strings envueltos en `{% trans %}`
- Archivo `.po` español completo
- Lighthouse score > 90 en mobile
- WAI-ARIA en componentes interactivos (lightbox, modales)
- Keyboard navigation
- README final + runbook operacional
- Tests E2E con Playwright para flujos críticos

---

## 7. Reglas de interacción conmigo (Jair)

- **Trabajo desde iPad** la mayoría del tiempo. Eso significa que comandos `bash` largos los corro yo en Claude Code. **Verificá tu trabajo con tests + linter, no esperés que yo lo pruebe manualmente cada vez.**
- **No soy developer profesional**. Cuando expliques una decisión técnica, **explicá el "por qué" en términos de negocio**, no solo en términos técnicos.
- **Si una decisión no está en este documento, preguntame antes de inventar**. No asumas.
- **Si encontrás algo en este documento que está mal o desactualizado, decímelo y proponé el cambio**.
- **Al final de cada fase**:
  1. Corré todos los tests + linter (todo en verde)
  2. Hacé commit con mensaje descriptivo
  3. Hacé push
  4. Hacé deploy a Railway si aplica
  5. Resumime en español qué hiciste, qué decisiones tomaste fuera del plan (si las hubo), y qué falta
  6. Esperá mi OK antes de empezar la siguiente fase
- **Hablame en español** rioplatense/latinoamericano usando "vos" (no "tú").
- **No uses emojis** salvo cuando agreguen información (ej. ✅/❌ en checklist). No los uses para decorar.

---

## 8. Cosas que NUNCA hacés sin pedirme permiso explícito

- Cambiar el stack (Django, HTMX, R2, Railway, Postgres, etc.)
- Agregar dependencias pesadas (>50MB, o que requieran compilación nativa compleja)
- Modificar este archivo (`CLAUDE.md`)
- Borrar tests existentes
- Hacer migrations destructivas (DROP COLUMN, etc.) sin confirmación
- Hacer deploy a producción si hay tests en rojo
- Hardcodear credenciales, API keys, o el nombre "RunFoto" (siempre via env vars o `site_name`)
- Commitear archivos de secrets/`.env`

---

## 9. Glosario rápido

- **Dorsal**: número que el corredor lleva en la camiseta (en inglés "bib"). Lo detectamos con OCR.
- **Evento**: una carrera específica (ej. "Maratón de San Salvador 2026").
- **Fotógrafo**: persona que toma fotos del evento. NO tiene cuenta, accede por token.
- **Link de upload**: URL única tipo `/u/abc123x` que se genera por fotógrafo+evento.
- **Preview**: versión reducida con marca de agua que se muestra públicamente.
- **Original**: archivo subido por el fotógrafo, alta resolución, sin marca de agua. Solo accesible via URL firmada al descargar.
- **Embedding**: vector de 512 dimensiones que representa una cara. Permite buscar caras parecidas.
- **DTE/NextBill**: otro proyecto del mismo Jair, NO relacionado con RunFoto.

---

**Última actualización**: Fase 7 (i18n + accesibilidad + tests E2E + polish final). El código de las 8 fases está completo. El tag `v1.0.0` y la declaración de "production ready" quedan **pendientes de los chequeos manuales de Jair** que no se pueden automatizar: Lighthouse ≥95 (a11y) y ≥85 (perf mobile), prueba en dispositivo real, screen reader, y una pasada de un usuario real. Actualizar este archivo al final de cada fase con aprendizajes y decisiones nuevas.

## Cambios introducidos en Fase 1
- Política de retención escalonada de eventos (§3) — nueva tabla con 4 ventanas temporales y el flag `permanent_archive`.
- `Event` extendido (§4) con 8 estados, 3 visibilidades, fechas de retención y counters denormalizados.
- `User(AbstractUser)` introducido en `apps.core` (`AUTH_USER_MODEL = 'core.User'`).
- `EncryptedCharField` custom en `apps/core/fields.py` usando `cryptography.fernet` (sin dep nueva — `cryptography` ya entra como transitiva).
- Postgres: dev pg16 / prod pg18 (decisión documentada en §2). pgvector ≥0.7 anda en ambos.
- Admin custom: `django-unfold` (ADR 0002).

## Cambios introducidos en Fase 2
- **Portal de fotógrafo** (`/u/<token>/`) sin cuenta, autenticado por token URL único. Validación del hash sha256 en CADA request (no se confía en sesiones). 410 (token muerto) vs 403 (límite de fotos) distinguidos.
- **`UploadView` es `csrf_exempt`**: el token URL es la autenticación; no hay sesión que CSRF defienda. El rate limit por token + el hash sha256 son la defensa real. (Decisión nueva, no estaba en el plan.)
- **Storage R2** (`apps/photos/storage.py`): wrapper boto3 con upload / signed URL (TTL 15 min) / delete / delete_many. Si `R2_ENDPOINT_URL` está vacío → usa default AWS (para tests con `moto`).
- **Cloudflare R2**: un solo bucket `runfoto-prod` por ahora (Jair creó solo ese). Cuando haga falta separar dev/prod se crea `runfoto-dev`. Token con permiso "Object Read & Write" sobre el bucket.
- **Imaging** (`apps/photos/imaging.py`): preview 1200px WebP q80 con watermark diagonal (texto repetido rotado -30°), thumbnail 400px WebP q75, extracción de EXIF.
- **OCR** (ADR 0004): PaddleOCR primario + EasyOCR fallback. Heurística `is_bib_like` (1-6 chars, dígitos o letra+dígitos). Verificado E2E: detectó 10/10 dorsales sintéticos incl. alfanuméricos.
- **Celery**: `process_photo` (EXIF + preview + thumb → encadena OCR) + `run_ocr_on_photo`. Autoretry exponencial. **El worker en Railway todavía NO existe** (CLI/MCP tiran Unauthorized al conectar repo; lo crea Jair desde dashboard). Verificación E2E de Fase 2 se hizo corriendo el worker localmente apuntado a Redis+DB+R2 de Railway.
- **Deps nuevas**: paddleocr, paddlepaddle, easyocr (runtime); moto[s3] (dev). Imagen Docker ~3 GB (torch trae CUDA libs innecesarias — pendiente cambiar a `torch+cpu`). Worker necesita ≥1 GB RAM.
- **Pendiente para producción real**: crear servicios `worker` y `beat` en Railway. Hasta entonces, las fotos subidas quedan en `status=processing` sin procesar.

## Cambios introducidos en Fase 3
- **Landing pública** (`/`) + **galería de evento** (`/eventos/<slug>/`) + **lightbox** (`/eventos/<slug>/foto/<id>/`), replicando pantallas 1-6 del design system. Verificadas con screenshots en mobile (375px) + desktop.
- **Búsqueda por dorsal**: cache 5 min en Redis (IDs, no objetos, para no cachear signed URLs), normalización + validación de formato, empty state con **sugerencias OCR** (variantes 0/8/6/9, 1/7, 5/6/8, etc. que existen en el evento).
- **Rate limiting (ADR 0005)**: 60 búsquedas/h por IP, 10/día por (IP, evento, dorsal), 5 ZIPs/h por IP. Con `django_ratelimit.core.is_ratelimited` (API programática). **NO se creó modelo SearchLog** — solo `Event.search_count` denormalizado + Redis (decisión de privacidad).
- **Descarga ZIP**: modelo `ZipDownload` (apps/downloads), task `generate_zip` (baja originales de R2 → ZIP → sube a R2 → signed URL 1h), `cleanup_expired_zips` (beat cada hora). Verificado E2E: ZIP con 5 originales full-res **sin watermark**.
- **Estados de retención aplicados**: `public`/`live`/`upcoming` → galería completa; `public_closed`/`searchable_only` → solo búsqueda (`event_closed.html`); `archived`/`pending_deletion` → 404 amigable; `private`/`draft`/`deleted` → 404.
- **`Photo._presign` ahora usa R2 real** (boto3 signed URL 15 min) en vez del stub `r2://`. Devuelve `""` si R2 no está configurado (tests sin credentials).
- **SEO**: `sitemap.xml` (eventos públicos), `robots.txt` (bloquea /admin/, /u/, /descargas/), OG tags en `base.html`.
- **Selección múltiple**: Alpine.js con `sessionStorage` por evento. Pill flotante + bottom sheet de descarga con polling del estado del ZIP.
- **Bug Django**: los comentarios `{# #}` multilínea se renderizan como texto. Usar `{% comment %}` para multilínea. (Arreglados 3 casos.)
- **Cloudflare R2**: un solo bucket `runfoto-prod` (Jair no creó `runfoto-dev`). Todo apunta ahí por ahora.
- Cobertura global 85%. 215 tests (+1 slow de OCR excluido en CI).

## Cambios introducidos en Fase 4
- **Reconocimiento facial** (InsightFace `buffalo_l`, CPU): `apps/ml/face_recognition.py` con `extract_faces` (disco) y `embedding_from_bytes` (selfie en memoria). Embeddings 512-d normalizados L2.
- **Búsqueda por selfie SÍNCRONA** (`/eventos/<slug>/buscar-selfie/`): el embedding del selfie se procesa EN MEMORIA y se descarta — NUNCA se persiste ni pasa por Celery/Redis (decisión de privacidad, ADR 0006). Matching pgvector con `CosineDistance`, threshold 0.55, agrupado por confianza (alta/media/baja).
- **delete-my-data SÍNCRONO** (`/privacidad/borrar-mis-datos/`): extrae embedding en memoria, busca en TODOS los eventos (threshold 0.62 estricto), pasa sólo `photo_ids` (no biometría) a la task de borrado. Borra embeddings + bibs + R2 + Photo + AuditLog.
- **Blur de menores**: caras estimadas <16 → blur automático del preview (original intacto); caras <22 → `Photo.needs_minor_review` para revisión del admin (Fase 5). Si el blur falla → `processing_failed` (no se aprueba). Decisión de Jair: doble umbral + red de seguridad humana.
- **Retención 90 días**: `cleanup_old_embeddings` (Celery beat diario 3 AM) borra embeddings con `last_matched_at`>90d (o `created_at` si nunca matcheó). NO se desactiva sin migración + aprobación.
- **pgvector HNSW** (ya creado en Fase 1): verificado que las queries lo usan vía `EXPLAIN` (`Index Scan using face_embedding_hnsw_cos`). ADR 0007.
- **Banner de privacidad** en `base.html` (block desactivable en fullscreen). Página `/privacidad/` completa.
- **Reglas de privacidad cumplidas**: selfie/embedding del usuario nunca persistido, nunca por Redis, nunca loggeado completo, IP siempre hasheada. Verificado por tests.
- **Decisiones nuevas vs el prompt**: (1) selfie search + delete síncronos (el prompt los hacía con tasks; cambiado por privacidad — la biometría nunca toca el broker). (2) Campos nuevos `Photo.needs_minor_review` + `has_faces_detected` + status `processing_failed` (max_length status 16→24).
- **Verificación E2E** (caras GAN reales + buffalo_l): same-person 0.96-1.0 vs different 0.19-0.28; búsqueda 4/4 sin falsos positivos en 10ms con HNSW. Extracción ~0.18s/foto.
- **Deps nuevas**: insightface, onnxruntime, opencv-python-headless. El modelo buffalo_l (~280MB) se **pre-cachea en build-time** a `/opt/insightface` (`INSIGHTFACE_ROOT`), best-effort para no acoplar el deploy a la descarga externa.
- **Bug de prod #1 (cv2)**: el POST de selfie daba 500 en Railway (no en local) por `ImportError: libxcb.so.1` — InsightFace arrastra `opencv-python` (full, no headless) y su `cv2.so` necesita libs de sistema que la imagen slim no traía. Fix en `Dockerfile`: instalar `libgl1 libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6 libxrender1`. También se pre-cachea buffalo_l en build-time y gunicorn va con `--timeout 120`.
- **Bug de prod #2 (RAM) — NO resuelto, decisión de Jair pendiente**: el servicio `fotos` está **capado a 1 GB** y cargar buffalo_l necesita **~1.1 GB** aún optimizado (`--workers 1` + `allowed_modules=['detection','recognition','genderage']`, sin los 2 modelos de landmarks que no usamos). El OOM SIGKILLeaba el único worker → 502 que tiraba todo el sitio. **Mitigación aplicada**: feature flag `FACE_SEARCH_ENABLED` (default `true` local, `false` en Railway prod) que corta antes de cargar el modelo y muestra `public/face_unavailable.html` (503). Tab "Por selfie" oculto en prod. Para re-habilitar: subir RAM a ≥2 GB / cambiar a buffalo_s / microservicio aparte (ver runbook §Incidentes). **Jair eligió "dejarlo así por ahora"** (la búsqueda por dorsal, método principal, anda perfecto).
- **Verificación local del matching real**: con `allowed_modules`, misma persona 0.963 vs distinta 0.199 — el reconocimiento NO se degrada sin los landmarks (usa los 5 keypoints del detector). Embedding 512-d, edad y género OK.
- **Pendiente prod**: (1) worker + beat en Railway (sin ellos, el procesamiento facial de uploads, el borrado de delete-my-data y el cron de retención no corren en prod); (2) la RAM del web para re-habilitar `FACE_SEARCH_ENABLED`. Verificación de la pipeline se hizo con worker local.
- Cobertura: 263 tests, ml/privacy/search 85-93%.

## Cambios introducidos en Fase 5
- **Dashboard admin custom** (`apps/dashboard/`, montado en `/dashboard/`) — herramienta de uso diario. Reemplaza al Django admin (django-unfold) como interfaz principal; el admin queda como **fallback de emergencia movido a `/admin/django/`** (ADR 0008). Replica pantallas 08-13 del design system.
- **Acceso**: `StaffRequiredMixin` (login + `is_staff`). Un user sin permiso se **redirige al login** (override de `handle_no_permission`), no un 403 que revele el panel. Login custom en `/dashboard/login/` con rate limit 5/15min. Settings nuevos: `SESSION_SAVE_EVERY_REQUEST`, `SAMESITE=Strict` en base, `LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`.
- **Vistas** (paquete `apps/dashboard/views/`): home (stats+chart), eventos (list/create/detail con tabs HTMX/update), generar link (modal + QR + WhatsApp), cola de aprobación (grid multi-select + bulk + atajos de teclado Alpine), drawer de detalle (EXIF + dorsales editables vía HTMX), fotógrafos (revocar/regenerar), audit log, stats, configuración (cambiar pass + 2FA stub).
- **Counters de Event recalculados SÍNCRONO** (`services.recalculate_event_counters`), NO con Celery — el worker no corre en prod y son baratos (un par de COUNTs). Decisión nueva vs el prompt (que usaba `update_event_counters.delay`).
- **Stats SIN `SearchLog`** (decisión de Jair, respeta privacidad de Fase 3): las métricas se derivan de datos existentes (fotos por día/hora, totales por evento). NO hay "búsquedas por día" ni "top dorsales buscados" (requerirían guardar qué busca cada visitante). El prompt asumía `SearchLog` — se descartó.
- **QR**: librería `qrcode` (dep nueva, liviana) generando PNG base64 inline. **TODA acción admin va al `AuditLog`** (crear/editar evento, aprobar/rechazar/bulk, generar/revocar/regenerar link, editar dorsales, cambiar pass).
- **Decisiones nuevas vs el prompt**: (1) counters síncronos; (2) sin SearchLog; (3) pantallas "login" y "lista/form de eventos" no estaban en el design de referencia → construidas coherentes con el lenguaje visual; (4) en el tab "Links" del evento las acciones de gestión (revocar/regenerar) viven en la página de Fotógrafos (evita duplicar). El "merge de dorsales duplicados" del prompt quedó como listado (no merge) — pendiente si hace falta.
- **Bug sutil encontrado por tests**: el mensaje de rate limit del login no aparecía porque `form.add_error()` sobre el `AuthenticationForm` disparaba `authenticate()` y el error de auth quedaba primero. Fix: pasar el mensaje por contexto (`rate_limit_error`), sin tocar el form. También `select_for_update()`+`.distinct()` no es compatible en el bulk → se lockean IDs y se consulta aparte.
- **Cobertura**: 40 tests nuevos del dashboard (91% en `apps/dashboard/`), 303 tests totales. ruff/black/mypy/django-check limpios.
- **Pendiente prod (sin cambios)**: worker + beat en Railway; RAM para `FACE_SEARCH_ENABLED`. El dashboard NO depende de ninguno de los dos (recalcula counters síncrono).

## Cambios introducidos en Fase 6
- **Crons de retención + cleanup** (`apps/privacy/tasks.py`): `enforce_event_retention_policy` (live→public_closed→searchable_only→archived→pending_deletion, respeta `permanent_archive`, idempotente, AuditLog por transición) + `delete_event_photos_permanently` (borra R2+embeddings+bibs+photos, deja `Event status=deleted`, idempotente). Más `cleanup_expired_photographer_links`, `cleanup_old_audit_logs` (2 años — única política que permite borrar logs), `cleanup_failed_processing` (stuck >1h), `cleanup_orphaned_r2_objects` (alerta si >100, no borra). `CELERY_BEAT_SCHEDULE` ampliado (8 tasks, horarios en runbook).
- **Hardening seguridad**: CSP con `django-csp` 4.x en `base.py` (aplica dev+prod; `script-src` incluye unpkg + `unsafe-inline` (scripts inline) + `unsafe-eval` (Alpine evalúa sus directivas con `new Function()` — sin esto se rompe TODA su interactividad en el navegador real); `img-src data:` para QR; sin Google Fonts). prod.py: `SECURE_BROWSER_XSS_FILTER`, Sentry con `before_send=filter_sensitive_data` (filtra embeddings/tokens/selfies) + `RedisIntegration` + `release=GIT_SHA`. ADR 0009.
- **Bug encontrado al verificar CSP — hash SRI de Alpine mal** (`templates/base.html`): el `integrity=` de Alpine nunca coincidió con el archivo de unpkg (paquete npm inmutable → hash mal escrito desde el inicio), así que **Alpine jamás se ejecutó en un navegador real** y toda su interactividad (multi-select, lightbox, sheet de descarga, menú/drawer del dashboard) estaba silenciosamente rota desde Fase 3. No se detectó porque las verificaciones previas fueron por screenshots (render estático), no interacción. Corregido el hash + verificado en navegador (Alpine inicializa, evalúa y reacciona). Recomendación a futuro: auto-hospedar htmx+alpine en `static/` (como las fuentes) → sin dependencia de unpkg, sin mantenimiento de hashes SRI, CSP más estricta. Anotado como tarea separada.
- **Logging JSON** en prod (`python-json-logger`); texto legible en dev.
- **IP centralizada** (`apps/core/utils.py`): `anonymize_ip` (movido de core/models, re-exportado) + `hash_ip` con **salt diaria** (el hash de una IP cambia cada día → no se puede correlacionar actividad en el tiempo).
- **Health checks profundos**: `/healthz` (db/redis/r2/celery_workers/celery_beat; 503 SÓLO si DB o Redis caen — r2/celery son informativos para no tumbar el deploy sin worker) + `/healthz/lite` (sólo DB) que es el probe de Railway (cambiado en Dockerfile + railway.toml). `SECURE_REDIRECT_EXEMPT` ampliado a `^healthz`.
- **Páginas de error custom** (`templates/errors/`): 404/410/429/500 self-contained (el 500 NO usa context processors). `handler404`/`handler500` en config/urls. Django admin movido ya estaba en `/admin/django/`.
- **Páginas legales**: `/terminos/`, `/cookies/`, `/contacto/` (informativa, SIN form de email — CLAUDE.md "nada de email"). `/privacidad/` ya existía.
- **Backup de DB** (ADR 0010): comando `backup_db` + task `core.backup_database` (beat 1 AM), pg_dump→gzip→R2 (`backups/db/`, retención 30d), resiliente. **PRIMARIO = snapshots de Railway** (el backup a R2 necesita `postgresql-client-18` en la imagen, pendiente — no agregué PGDG al Docker para no arriesgar deploys).
- **Decisiones nuevas vs el prompt**: (1) CSP en `base.py` (no solo prod) para testearla y consistencia; (2) `/contacto/` informativa sin email; (3) NO toqué el Dockerfile con repos PGDG (riesgo) → backup a R2 documentado como pendiente, snapshots de Railway como primario; (4) `/healthz` no devuelve 503 por falta de worker (sería ruido — Railway usa `/healthz/lite`).
- **Deps nuevas**: django-csp (4.0), python-json-logger (4.1). Ambas livianas.
- **Verificación E2E**: cadena de retención completa con evento sintético (60 fotos) → `live`…→`deleted` con fotos+keys borradas. enforce ~50ms; delete_event ~1s/60 fotos. CSP header verificado (unpkg, data:, `unsafe-eval`) Y la interactividad de Alpine probada en navegador real (galería: `x-data` inicializa, `x-show` reacciona — antes del fix de `unsafe-eval` la consola se llenaba de `Alpine Expression Error`). securityheaders.com: pendiente de medir en prod (lo hace Jair).
- **Cobertura**: apps/core 93.6% · apps/privacy 90.7% (≥85% requerido) · global 87.4%. ~50 tests nuevos. 354 tests totales (353 pass + 1 slow deselected). ruff/black/mypy(166)/django-check limpios.
- **Pendiente prod (CRÍTICO)**: worker + beat en Railway. Sin ellos, NINGÚN cron de Fase 6 corre en prod (retención, cleanups, backup). Todo el código está listo y verificado local. Esto es lo principal a destrabar para que Fase 6 sirva en producción.

## Cambios introducidos en Fase 7
- **i18n completo**: catálogo `es` con **575 mensajes** (`msgstr == msgid` por ser idioma fuente, llenado con `msgen`), `en` placeholder vacío (listo para traducir sin tocar templates). `LocaleMiddleware` + `set_language`. Al agregar strings nuevos de a11y, `makemessages` marcó 4 entradas `fuzzy` (aria-labels que matchearon a strings parecidas, p.ej. "Número de dorsal" → "Tu número de dorsal"); se corrigieron con `polib` (defuzzy + `msgstr=msgid`) para que el aria-label se anuncie como se escribió. **Los `.mo` se commitean** (los tests de i18n los leen). 7 tests.
- **Accesibilidad**: skip link "Saltar al contenido", landmark `<main id=main-content>` (bloque `layout` en `base.html`), `:focus-visible` (anillo naranja, sólo teclado), `prefers-reduced-motion`, ARIA en lightbox + bottom sheet (`role=dialog`/`aria-modal`/Esc), `aria-label` en input de dorsal e íconos-botón (+ `aria-hidden` en sus SVG), un `<h1>` por página. **Contraste**: `text-3` `#6b6b70` → `#8a8a93` (WCAG AA). 8 tests estructurales (`tests/a11y/`). La auditoría Lighthouse/axe completa + screen reader la corre Jair (no se puede automatizar el número de Lighthouse acá).
- **Performance**: `loading="lazy"` + `decoding="async"` en grillas de fotos (la galería pública ya lo tenía), `font-display: swap` (ya estaba). **`hx-boost` NO se agregó** (decisión): reemplaza el `<body>` en cada navegación y puede desestabilizar Alpine (recién recuperado en Fase 6); beneficio marginal en un SSR chico.
- **Presupuesto de bundle en CI** (`scripts/check_bundle_size.sh`): CSS ≤ 90 KB (hoy ~52 KB). El job de CI ahora compila Tailwind (valida que el build no se rompió) y corre el presupuesto.
- **PWA**: `manifest.webmanifest` **dinámico** (TemplateView con `content_type=application/manifest+json`, usa `{{ site_name }}` para no hardcodear "RunFoto" — respeta §8). Iconos generados con Pillow (192/512/maskable/apple-touch/favicon): fondo oscuro + cuadrado naranja del wordmark + 3 líneas de velocidad (sin depender de fuentes, que son woff2 y Pillow no rasteriza). `theme_color` oscuro (`#0A0A0B`), no naranja, para no chocar con la UI dark. **Sin service worker** (decisión): el manifest+iconos ya hacen el sitio instalable; un SW agrega complejidad de cache que no se justifica.
- **SEO**: JSON-LD `schema.org/SportsEvent` en páginas de evento (name/startDate/location/image/organizer, con `escapejs`). Sobre el `sitemap.xml`/`robots.txt`/OG ya existentes de Fase 3.
- **Tests E2E (Playwright)** (`tests/e2e/`, extra `e2e` en pyproject, job de CI aparte): 5 flujos en Chromium real contra `live_server` — dorsal con resultados, empty state, evento archivado bloqueado, token vencido (410), login admin. Marcados `@pytest.mark.e2e` + `django_db(transaction=True)` (live_server necesita datos commiteados). `DJANGO_ALLOW_ASYNC_UNSAFE=1` en el conftest (Playwright sync corre en un event loop de greenlets → falso positivo del guard async de Django). El job principal de tests corre `-m "not slow and not e2e"`; si Playwright no está instalado, los E2E ni se colectan (`collect_ignore`).
- **Decisiones nuevas vs el prompt**: (1) sin `hx-boost`; (2) sin service worker; (3) E2E acotado a flujos que NO necesitan worker/InsightFace (la descarga de ZIP y el selfie quedan para cuando el worker corra en prod; ya están cubiertos por tests unit/integración); (4) manifest dinámico en vez de `static/manifest.json` (para no hardcodear el nombre); (5) `theme_color` oscuro en vez del naranja del prompt.
- **Verificación**: 368 tests (no-e2e) + 5 E2E en verde, 1 slow + 5 e2e deselected. Cobertura global **87.4%** (≥85% pedido). ruff/ruff-format/black/mypy(175)/django-check limpios. **Pendiente de Jair (manual, no automatizable)**: Lighthouse mobile (a11y ≥95, perf ≥85), axe/WAVE en navegador, screen reader (VoiceOver/NVDA), prueba en iPad/celular real, prueba con un usuario no técnico, stress test. Recién después de eso: **tag `v1.0.0`** y declarar "production ready".
- **Rebrand a "find your foto" + logo visor (post-Fase 7, a pedido de Jair)**: wordmark nuevo = símbolo **visor** (esquinas de enfoque de cámara + cuadrado naranja = la firma) + nombre en **dos tonos** derivado de `site_name` (context processor agrega `site_name_prefix`/`site_name_last`, split en la última palabra). Iconos PWA/favicon regenerados desde el visor (renderizando el SVG, tile `#17171A`). `SITE_NAME` default → "find your foto" (+ `ci.yml`). Páginas de error self-contained + subtítulo del login actualizados. **PENDIENTE Jair**: actualizar la env var `SITE_NAME` en Railway a `find your foto` — hoy prod muestra el logo + iconos nuevos pero el TEXTO sigue "RunFoto" porque la env var pisa el default. Logo elegido entre 6 conceptos (visor/apertura/lupa/meta/pin/dorsal) generados en Claude Design.
- **Auditoría a11y con axe-core en navegador real (Fase 7)**: **páginas públicas con 0 violaciones** (home, galería, búsqueda por dorsal, selfie, lightbox, borrar-mis-datos, términos). La cola de aprobación del dashboard tenía botones de selección y selects de filtro **sin nombre accesible** → corregido con `aria-label` (0 violaciones tras el fix, verificado). **Flag abierto (decisión de marca de Jair)**: el botón CTA `.rf-cta` tiene texto blanco sobre naranja `#FC5200` = contraste **3.3:1** (<4.5 AA para texto chico). Opciones: oscurecer el naranja sólo de los botones, usar texto oscuro sobre naranja, o aceptarlo (pasa como texto grande/bold). No se tocó el color de marca sin tu OK.
- **Pendiente prod (sin cambios respecto a Fase 6)**: worker + beat en Railway; RAM del web para reactivar `FACE_SEARCH_ENABLED`. Nada de Fase 7 depende de ellos.

## Cambios post-Fase 7 — Worker + Beat en producción (2026-06-05)

**El gran pendiente de las Fases 2-7 quedó RESUELTO**: ya corren `worker` y `beat` de Celery en Railway. Con esto, en prod ya funcionan: el procesamiento de uploads (preview/thumbnail + OCR de dorsal), la descarga de ZIP, el borrado de delete-my-data, y todos los crons de retención/cleanup/backup de Fase 6.

- **Patrón de 1 imagen / 3 roles**: los 3 servicios (`fotos` web, `worker`, `beat`) corren el MISMO repo y el MISMO Dockerfile. Un entrypoint único (`scripts/entrypoint.sh`) se ramifica por la env var `PROCESS_TYPE` (`web` default → migraciones + gunicorn; `worker` → `celery -A config worker --concurrency 1`; `beat` → `celery -A config beat --schedule /tmp/celerybeat-schedule`). Así no hay que mantener un start-command por servicio en el dashboard.
- **Healthcheck sacado del `railway.toml`**: era global a los 3 servicios y worker/beat no sirven HTTP → su deploy fallaría siempre. El web igual queda protegido porque Railway no promueve un deploy cuyo contenedor crashea al arrancar. (Si en el futuro se quiere healthcheck sólo para el web, hay que setearlo por servicio vía dashboard/API, no en railway.toml.)
- **Blur de menores DESACTIVADO en prod (decisión explícita de Jair)**: nuevo flag `FACE_PROCESSING_ENABLED` (default = `FACE_SEARCH_ENABLED`, o sea `false` en prod) gatea el paso facial del upload en `process_photo`. En prod el worker NO carga InsightFace (~1 GB) → procesa liviano y barato (preview/thumbnail + OCR), PERO no hay blur de menores ni extracción de embeddings. **Esto override la regla "non-negotiable" de blur de menores (§3 / Fase 4)** — fue decisión del dueño. Local/dev siguen con face on (los tests no cambian). Para re-activar: poner `FACE_PROCESSING_ENABLED=true` en el worker (y subir su RAM).
- **Portal del fotógrafo arreglado** ("se veía negro"): "Subidas recientes" ahora muestra el thumbnail real (`<img>` con signed URL de R2; antes era sólo un gradiente oscuro aunque la foto estuviera procesada). El estado pasó de un `setTimeout` falso de 4s a **polling real** a un endpoint nuevo `/u/<token>/status/` (`PhotographerUploadStatusView`, filtra por el link del token → un fotógrafo sólo ve sus propias fotos). Verificado en navegador: thumbnail carga desde R2, sin errores de CSP. Tests del endpoint en `tests/photographers/test_upload_status.py`.
- **Variables**: worker/beat copian las 22 del web (todas menos `RAILWAY_*` que Railway inyecta por servicio, y `DJANGO_SUPERUSER_*` que sólo bootstrapea el web) + `PROCESS_TYPE`.
- **Railway auth (aprendizaje operativo)**: el token de browser del CLI/MCP **se vence seguido** → da `Unauthorized` en escrituras (las lecturas a veces andan por una ventana de gracia). Solución durable: **API token de cuenta** (Railway → Account Settings → Tokens) usado como env var `RAILWAY_API_TOKEN`. Además, `railway add` NO acepta `-p/-e` (no resuelve el proyecto con API token) → los servicios se crearon por la **API GraphQL** (`serviceCreate` → `variableCollectionUpsert` → `serviceInstanceDeployV2`) con **curl** (Cloudflare bloquea el User-Agent de `urllib` con `error 1010`). El MCP de Railway quedó muerto toda la sesión (token cacheado vencido, no se refresca del CLI).
- **IDs Railway**: env `production` = `b48c37f0-dab0-4627-b95c-a20db2862579`; servicio `worker` = `1846c52a-57c3-4a8b-b4ec-1cc200a8e652`; servicio `beat` = `0a364656-8700-4f69-bac0-b91c50cd722b`; web `fotos` = `5dec515d-7408-46ae-91ac-d2325d6d92ad`.
- **Nota**: los 3 servicios redeployan en cada `git push` (todos trackean `main`). Es esperado; Railway cachea el build, así que worker/beat rebuildan rápido.
- **Pendiente Jair**: (1) poner un **límite de gasto** en Railway (Settings → Usage Limits) — ahora hay 3 servicios corriendo; (2) cambiar la pass temporal del admin; (3) **revocar el API token** de Railway cuando no haga falta. (El `SITE_NAME=find your foto` ya quedó seteado en el web y prod muestra el logo + texto nuevos — esa pendiente de Fase 7 está resuelta.)

## Fixes post-worker — fecha, OCR, badge (2026-06-05)

Tres cosas que reportó Jair usando el sistema con el worker ya andando:

- **La fecha del evento "se perdía" al editar (NO era la BD)**: `EventForm` usaba widgets `type=date`/`datetime-local` SIN `format` explícito → con `LANGUAGE_CODE=es` Django renderizaba el valor como `d/m/Y` y el input HTML5 (que exige ISO `YYYY-MM-DD`) lo dejaba **vacío** al editar, dando la sensación de tener que re-poner la fecha cada vez. Fix: `format` + `input_formats` ISO en el form (`apps/dashboard/forms.py`). **La fecha SIEMPRE estuvo bien guardada** — era sólo display. Test de regresión en `tests/dashboard/test_events.py`.
- **OCR detectaba 1 dorsal y erróneo**: en una foto real (4 corredores) Paddle leyó "118" (de un cartel/fondo) con conf 1.0 y perdió los reales. Debilidad encontrada: EasyOCR sólo corría si Paddle devolvía CERO, así que ese falso positivo se "tragaba" el fallback. Fix: `detect_bibs` corre EasyOCR también cuando Paddle encuentra **<2** candidatos (mejor recall, sin romper el test de dedup). OCR sigue siendo best-effort → corrección manual del admin (tab "Dorsales"). **Nota de producto**: la búsqueda por selfie sigue apagada en prod (RAM), así que **el OCR es hoy el ÚNICO método de búsqueda**; si su recall no alcanza para que los corredores se encuentren, reconsiderar reactivar selfie (subir RAM del web / microservicio).
- **Badge "En vivo" → "Galería abierta"** (decisión de Jair): el "En vivo" con puntito pulsante implicaba tiempo real / carrera en curso, confuso para un evento cuya carrera ya pasó pero cuya galería sigue abierta. Cambiado en el badge de home + galería de evento + el conteo del hero + el label del estado `LIVE` del modelo (también el pill del dashboard, que usa `get_status_display`). Migración cosmética `0002_alter_event_status` (sólo choices) + catálogo `es` actualizado con polib (quirúrgico, sin re-numerar todo). Verificado en prod. **Los eventos demo viejos** (Maratón Antigua, Trail Ipala — de Guatemala, seed que quedó en prod) **se DEJAN como están** (decisión de Jair); ahora muestran "Galería abierta".

## Búsqueda por selfie RE-ACTIVADA en prod (2026-06-05)

Jair pasó a Hobby y decidió bancar el costo para tener búsqueda por selfie (subir foto de una persona → encontrar sus fotos). Activado con **buffalo_l** (modelo completo, mejor precisión):

- **Cómo se activó**: `FACE_SEARCH_ENABLED=true` en el **web** (gatea la vista de búsqueda) y en el **worker** (cascada a `FACE_PROCESSING_ENABLED` → indexa caras en cada upload). Beat no lo necesita. Seteado vía API GraphQL (`variableUpsert`) + redeploy.
- **RAM (aclaración importante)**: en Hobby **NO se asigna RAM a mano** — cada servicio usa hasta 8 GB automáticamente y se cobra por uso real. El "cap de 1 GB" de Fase 4 era del plan **trial**; Hobby lo levanta. O sea: "agregar RAM" = prender la función. **Verificado sin OOM**: el web carga buffalo_l (~28 s la 1ª vez) y `healthz` sigue 200; el worker carga el modelo y extrae embeddings sin morir.
- **Verificación E2E en prod**: (1) web — `POST` de un selfie con varias caras → responde "varias caras" (el modelo cargó + detectó); (2) worker — reprocesé la foto real `id=162` y guardó **11 embeddings** (512-d, edades 27-46, sin menores); (3) búsqueda — `CosineDistance` de pgvector devuelve la foto correcta (self-match 100%). Las 3 piezas (detección, indexado, matching) confirmadas en vivo.
- **Reproceso sin SSH**: `railway ssh` pide SSH key registrada (no había). Se encoló `process_photo` directo a la **cola de prod** vía el **proxy público de Redis** (`REDIS_PUBLIC_URL` / `kodama.proxy.rlwy.net`) con un `Celery(broker=...).send_task(...)` desde local. Útil como patrón para encolar tasks en prod sin SSH.
- **Blur de menores volvió a estar ON**: es parte del paso facial; al re-activar `FACE_PROCESSING` el blur vuelve. En `id=162` (11 adultos) no se gatilló. **Jair había dicho "blur no necesario"** (cuando se apagó por costo) — si lo sigue sin querer, se puede gatear el blur aparte (mantener embeddings, saltar `regenerate_preview_with_minor_blur`). Pendiente de su decisión; por ahora ON (más seguro).
- **OCR mejorado confirmado en vivo**: al reprocesar `id=162`, EasyOCR sumó dorsales (1223, 1225, …) que Paddle solo no veía (antes daba sólo "118"). También suma ruido de baja confianza → el admin cura.
- **Costo**: la cuenta de Railway sube a **~$30-40/mes** (el modelo facial corre en web + worker). **Más urgente que nunca: poner el límite de gasto** (Settings → Usage Limits).
- **Nota**: la foto `id=162` quedó en `pending_review` tras el reproceso (process_photo la resetea) — Jair la re-aprueba con los dorsales/caras nuevos. Y para probar el selfie end-to-end necesita un evento **público + searchable** con fotos aprobadas con caras (el evento "prueba" es draft; los demo son sintéticos sin caras).

## Blur OFF + UX de subida mobile + auditoría de aprobación (2026-06-05)

- **Blur de menores APAGADO definitivamente en prod** (Jair: "el blur nunca debe aparecer"). Nuevo flag `MINOR_BLUR_ENABLED` (default `True` para local/tests; `false` en el worker de prod). Gatea sólo `regenerate_preview_with_minor_blur` en `run_face_recognition_on_photo` — el **indexado de embeddings (selfie) sigue intacto**, sólo se saltea la regeneración con blur. Esto ratifica el override de la regla "non-negotiable" de §3/Fase 4 (decisión del dueño).
- **UX de subida arreglada (el bug real era mobile)**: el indicador de estado de cada foto en la cola tenía `hidden md:inline-flex` → **invisible en mobile**. Como Jair sube desde iPad, veía la barra pero no "cuáles se subieron" (de ahí "se suben algunas, pero no hay barra"). El **backend siempre estuvo bien** (las 3 subidas de prueba → 200). Rediseño **mobile-first** de la cola (`templates/photographer/portal.html`): layout flex, **estado SIEMPRE visible con ✓/✗** + punto pulsante, barra de progreso, resumen "X listas · Y en curso · Z con error", thumbnail real al terminar. Verificado en navegador a 375px. **Auto-reintento con backoff si el server devuelve 429** (rate limit en lotes grandes) → ninguna foto se "pierde". Polling de estado subido a 40 ciclos (~2 min) porque el worker tarda más con el modelo facial encendido.
- **Auditoría del flujo de aprobación**: verificado E2E con test client — cola de pendientes (200) → aprobar single → `approved` → aprobar **bulk** → ambas `approved` → **la galería pública muestra las aprobadas**. Counters OK. **Sin bugs**; el código de Fase 5 ya estaba correcto.
- **Patrón de auditoría**: para auditar prod sin SSH se usó el **proxy público de Postgres** (`kodama.proxy.rlwy.net`, en `.claude/launch.json` config `runfoto-preview`) con `DATABASE_URL` override + `settings.ALLOWED_HOSTS=['*']` para el test client en `manage.py shell`. Y el proxy de Redis para encolar tasks. Útiles para operar/diagnosticar prod desde local.

## Soporte HEIC en la subida (2026-06-06)

**El bug REAL de "subir en Mac es lo mismo"** (distinto al de mobile que se arregló antes): `handleFiles` del portal descartaba **en silencio** todo archivo que no terminara en `.jpg/.jpeg`. Las fotos de **iPhone/Mac son HEIC** → desaparecían sin avisar ("se suben algunas, no hay indicación"). El backend también era JPEG-only (`is_valid_jpeg`).

- **`ensure_jpeg()` en `apps/photos/imaging.py`**: JPEG passthrough (sin re-encodear); HEIC/PNG/WEBP/etc. → convierte a JPEG. El original guardado en R2 es **siempre JPEG** (descarga universal + todo el pipeline lo asume). `register_heif_opener()` de **pillow-heif** registrado al importar imaging (best-effort).
- **`UploadView`** usa `ensure_jpeg` en vez de `is_valid_jpeg`. No-imagen → 400 `invalid_format`.
- **Portal**: `accept="image/*"`, y `handleFiles` **ya no descarta en silencio** — cada archivo aparece en la cola; lo que no es imagen se marca con **error visible** ("Solo imágenes").
- **Dep nueva**: `pillow-heif>=0.18` (wheel manylinux, **sin libheif del sistema** → bajo riesgo de deploy; verificado: build de Railway OK). Agregada al override de mypy.
- **Verificado E2E en prod**: POST de un HEIC real → `200` + key `.jpg` (convertido). Test `test_upload_converts_heic_to_jpeg`.
- **Nota**: la conversión corre **síncrona en el web** (~1-2s por HEIC). El web también carga InsightFace para el selfie; si el volumen de HEIC fuera alto, evaluar mover la conversión al worker. Por ahora OK para la escala.

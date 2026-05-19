# CLAUDE.md — RunFoto

> Este archivo es el contexto persistente del proyecto. Claude Code lo lee al inicio de cada sesión.
> Si encontrás algo desactualizado o contradictorio, **pará y preguntá antes de avanzar**.

---

## 1. Qué es RunFoto

Plataforma web **gratuita** de fotos de carreras deportivas para el mercado centroamericano (Guatemala/El Salvador inicial). Permite a corredores buscar y descargar fotos suyas de eventos de running, trail, ultra, ciclismo y similares — usando **dos métodos de búsqueda**:

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
- **PostgreSQL 16** + **pgvector** extension (para embeddings faciales)
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
- **Retención de embeddings**: **90 días** desde el último uso. Cron job diario (Celery beat) que borra embeddings inactivos.
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
    status: choices(draft, upcoming, live, closed)
    visibility: choices(public, unlisted)
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
class AuditLog:
    user: FK User (nullable, for anonymous events)
    action: str  # 'photo.approved', 'event.created', 'data.deleted'
    target_type: str
    target_id: str
    metadata: JSONField
    ip_address: str (anonymized)
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
- **Evento**: una carrera específica (ej. "Maratón Guatemala 2026").
- **Fotógrafo**: persona que toma fotos del evento. NO tiene cuenta, accede por token.
- **Link de upload**: URL única tipo `/u/abc123x` que se genera por fotógrafo+evento.
- **Preview**: versión reducida con marca de agua que se muestra públicamente.
- **Original**: archivo subido por el fotógrafo, alta resolución, sin marca de agua. Solo accesible via URL firmada al descargar.
- **Embedding**: vector de 512 dimensiones que representa una cara. Permite buscar caras parecidas.
- **DTE/NextBill**: otro proyecto del mismo Jair, NO relacionado con RunFoto.

---

**Última actualización**: Fase 0 (initial setup). Actualizar este archivo al final de cada fase con aprendizajes y decisiones nuevas.

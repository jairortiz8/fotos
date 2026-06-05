# Changelog

Todos los cambios relevantes de RunFoto, fase por fase.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y el versionado es semántico, donde **cada versión menor (`0.N.0`) corresponde a
una fase del plan de construcción** (ver `CLAUDE.md` §6). Las versiones son
lógicas (marcan el cierre de cada fase); el campo `version` de `pyproject.toml`
todavía está en `0.0.1` y lo sube Jair cuando corresponda.

## [1.0.0] — Production ready (Fase 7) — En progreso, pendiente de tag (pendiente)

> Esta entrada está **en progreso**. El tag `v1.0.0` lo crea Jair **después** de
> los chequeos manuales que no se pueden automatizar: Lighthouse > 90 en mobile,
> prueba en un dispositivo real, y una pasada de un usuario real. Por eso no
> lleva fecha todavía.

### Added
- **i18n completo**: todos los strings de UI envueltos en `{% trans %}` /
  `gettext()`. Catálogo `es` completo (**575 mensajes**, `msgstr == msgid` por ser
  idioma fuente); `en` queda como placeholder vacío (listo para traducir sin
  tocar templates). Cambio de idioma vía `set_language`. 7 tests de i18n.
- **Accesibilidad**: skip link "Saltar al contenido", landmark `<main>`, foco
  visible por teclado (`:focus-visible`), `prefers-reduced-motion`, WAI-ARIA en
  lightbox y bottom sheet (`role=dialog`, `aria-modal`, Esc cierra), `aria-label`
  en inputs (dorsal) e íconos-botón, jerarquía de headings (un `<h1>` por página).
  Contraste subido a WCAG AA (`text-3` `#6b6b70` → `#8a8a93`). 8 tests
  estructurales de a11y. (La auditoría Lighthouse/axe completa la corre Jair.)
- **Performance mobile**: `loading="lazy"` + `decoding="async"` en las grillas de
  fotos, `font-display: swap` en todas las fuentes auto-hospedadas, y
  **presupuesto de tamaño de bundle en CI** (`scripts/check_bundle_size.sh`, CSS
  ≤ 90 KB; hoy ~52 KB).
- **Tests E2E con Playwright** (`tests/e2e/`, job de CI aparte): 5 flujos en un
  navegador real — búsqueda por dorsal con resultados, empty state, evento
  archivado bloqueado, portal con token vencido (410), y login del admin.
- **PWA**: `manifest.webmanifest` dinámico (usa `site_name`, no hardcodea el
  nombre) + iconos generados (192 / 512 / maskable / apple-touch / favicon) +
  links en `base.html`. (Sin service worker por ahora — ver Decisiones.)
- **SEO**: datos estructurados `schema.org/SportsEvent` (JSON-LD) en las páginas
  de evento, sobre el `sitemap.xml` / `robots.txt` / OG ya existentes.
- **Documentación final**: este `CHANGELOG.md`, `docs/deployment.md`,
  `docs/troubleshooting.md`, `docs/api.md`, y README finalizado.

### Decisiones fuera del plan (Fase 7)
- **Sin `hx-boost`**: el prompt lo sugería, pero reemplaza el `<body>` en cada
  navegación y puede desestabilizar Alpine (que recién recuperamos en Fase 6).
  Para un sitio SSR chico el beneficio es marginal; se omitió a propósito.
- **Sin service worker**: el manifest + iconos ya hacen el sitio instalable. Un
  SW agrega complejidad de cache/invalidación que no se justifica todavía.
- **E2E acotado a flujos sin worker/ML**: descarga de ZIP y búsqueda por selfie
  necesitan Celery / InsightFace; sus E2E quedan para cuando el worker corra en
  prod. Igual están cubiertos por tests unitarios/integración.

### Pendiente para que la versión sea "production ready" de verdad
- **Worker + beat de Celery en Railway** (heredado de fases anteriores). Sin
  ellos no corre nada async en prod: procesamiento de uploads (OCR + caras),
  crons de retención/cleanup, backup a R2. El código está listo y verificado en
  local.
- **RAM del servicio web** para reactivar `FACE_SEARCH_ENABLED` (búsqueda por
  selfie) en prod (necesita ≥2 GB; hoy está capado a 1 GB).

## [0.7.0] — Privacidad + retención + hardening (Fase 6)

### Added
- **Crons de retención y cleanup** (`apps/privacy/tasks.py`):
  - `enforce_event_retention_policy`: avanza el estado de los eventos según las
    fechas (`live` → `public_closed` → `searchable_only` → `archived` →
    `pending_deletion`). Respeta `permanent_archive`, es idempotente y deja
    rastro en el `AuditLog` por cada transición.
  - `delete_event_photos_permanently`: borra R2 + embeddings + bibs + fotos y
    deja el evento en `status=deleted` (idempotente).
  - `cleanup_expired_photographer_links`, `cleanup_old_audit_logs` (2 años, la
    única política que permite borrar logs), `cleanup_failed_processing`
    (fotos atascadas > 1 h), `cleanup_orphaned_r2_objects` (alerta si > 100,
    no borra solo).
  - `CELERY_BEAT_SCHEDULE` ampliado a 8 tasks (horarios en `docs/runbook.md`).
- **Hardening de seguridad** (ADR 0009):
  - Content Security Policy con `django-csp` 4.x en `base.py` (aplica en dev y
    prod). `script-src` incluye `unpkg` + `'unsafe-inline'` + **`'unsafe-eval'`**
    (obligatorio para Alpine.js). `img-src` permite `data:` (para el QR).
    Sin Google Fonts (fuentes auto-hospedadas).
  - `SECURE_BROWSER_XSS_FILTER`, HSTS 1 año + preload, `X-Frame-Options=DENY`,
    `Referrer-Policy`, cookies `Secure`/`HttpOnly`/`SameSite=Strict`.
- **Sentry** en prod con `before_send=filter_sensitive_data` (filtra
  embeddings/tokens/selfies), `RedisIntegration`, y `release=GIT_SHA`.
- **Logging JSON** en prod (`python-json-logger`); texto legible en dev.
- **IP centralizada** (`apps/core/utils.py`): `anonymize_ip` + `hash_ip` con
  **salt diaria** (el hash de una IP cambia cada día → no se puede correlacionar
  actividad en el tiempo).
- **Health checks profundos**: `/healthz` (db / redis / r2 / celery_workers /
  celery_beat; 503 sólo si caen DB o Redis) + `/healthz/lite` (sólo DB) usado
  como probe de Railway.
- **Páginas de error custom** (`templates/errors/`): 404 / 410 / 429 / 500
  (el 500 es self-contained, sin context processors).
- **Páginas legales**: `/terminos/`, `/cookies/`, `/contacto/` (informativa, sin
  formulario de email — política "nada de email").
- **Backup de DB** (ADR 0010): comando `backup_db` + task `core.backup_database`
  (beat 1 AM), `pg_dump` → gzip → R2 (`backups/db/`, retención 30 días).
  **Primario = snapshots de Railway** (el dump a R2 necesita `postgresql-client-18`
  en la imagen, pendiente).

### Fixed
- **Bug del hash SRI de Alpine.js**: el `integrity="sha384-..."` de Alpine estaba
  mal desde Fase 3, así que el navegador **se negaba a ejecutar Alpine** y toda
  la interactividad (selección múltiple, lightbox, sheet de descarga, drawer del
  dashboard) estaba silenciosamente rota. No se había notado porque las
  verificaciones previas fueron con screenshots (render estático). Corregido el
  hash y verificado en navegador.
- Se agregó `'unsafe-eval'` al `script-src` de la CSP (Alpine evalúa sus
  directivas con `new Function()`; sin esto el navegador real bloquea toda la
  interactividad).

### Notes
- Cobertura ~92% en `apps/core` + `apps/privacy`. 354 tests totales.
- **Pendiente prod (crítico)**: worker + beat en Railway. Sin ellos ningún cron
  de esta fase corre en producción.

## [0.6.0] — Dashboard admin + cola de aprobación (Fase 5)

### Added
- **Dashboard admin custom** (`apps/dashboard/`, montado en `/dashboard/`) —
  herramienta de uso diario, reemplaza al Django admin como interfaz principal
  (ADR 0008). Replica las pantallas 08–13 del design system.
- **Django admin (django-unfold) movido a `/admin/django/`** como fallback de
  emergencia.
- **Acceso protegido**: `StaffRequiredMixin` (login + `is_staff`). Un usuario sin
  permiso se **redirige al login** (no un 403 que revele el panel). Login custom
  en `/dashboard/login/` con rate limit 5/15 min.
- **Vistas**: home (stats + chart), eventos (list / create / detail con tabs
  HTMX / update), generar link (modal + QR + mensaje de WhatsApp), cola de
  aprobación (grid multi-select + acciones en bloque + atajos de teclado),
  drawer de detalle (EXIF + dorsales editables vía HTMX), fotógrafos
  (revocar / regenerar), audit log, stats, configuración (cambiar password +
  stub de 2FA).
- **QR**: librería `qrcode` (dep nueva, liviana) generando PNG base64 inline.
- **Toda acción admin queda en el `AuditLog`** (crear/editar evento, aprobar/
  rechazar/bulk, generar/revocar/regenerar link, editar dorsales, cambiar pass).

### Changed
- **Counters de `Event` se recalculan síncrono** (`recalculate_event_counters`),
  no con Celery — el worker no corre en prod y son baratos (un par de COUNTs).
- **Stats sin `SearchLog`**: las métricas se derivan de datos existentes (fotos
  por día/hora, totales por evento). No hay "búsquedas por día" ni "top dorsales
  buscados" (requerirían guardar qué busca cada visitante; descartado por
  privacidad).

### Fixed
- El mensaje de rate limit del login no aparecía porque `form.add_error()` sobre
  `AuthenticationForm` disparaba `authenticate()` y el error de auth quedaba
  primero. Fix: pasar el mensaje por contexto (`rate_limit_error`).
- `select_for_update()` + `.distinct()` no era compatible en el bulk → se lockean
  los IDs y se consulta aparte.

### Notes
- 40 tests nuevos del dashboard (91% en `apps/dashboard/`), 303 tests totales.

## [0.5.0] — Búsqueda por selfie + reconocimiento facial (Fase 4)

### Added
- **Reconocimiento facial** (InsightFace `buffalo_l`, CPU) en
  `apps/ml/face_recognition.py`: `extract_faces` (foto en disco) y
  `embedding_from_bytes` (selfie en memoria). Embeddings 512-d normalizados L2.
- **Búsqueda por selfie SÍNCRONA** (`/eventos/<slug>/buscar-selfie/`): el
  embedding del selfie se procesa **en memoria y se descarta** — nunca se
  persiste ni pasa por Celery/Redis (decisión de privacidad, ADR 0006).
  Matching pgvector con `CosineDistance`, threshold 0.55.
- **`delete-my-data` SÍNCRONO** (`/privacidad/borrar-mis-datos/`): extrae el
  embedding en memoria, busca en TODOS los eventos (threshold 0.62 estricto) y
  pasa sólo `photo_ids` (no biometría) a la task de borrado.
- **Blur de menores**: caras estimadas < 16 → blur automático del preview
  (original intacto); caras < 22 → `Photo.needs_minor_review` para revisión
  humana del admin.
- **Retención 90 días**: `cleanup_old_embeddings` (beat diario 3 AM) borra
  embeddings con `last_matched_at` > 90 días.
- **pgvector HNSW** (índice coseno): verificado que las queries lo usan vía
  `EXPLAIN` (ADR 0007).
- **Banner de privacidad** en `base.html` + página `/privacidad/` completa.
- **Flag `FACE_SEARCH_ENABLED`** (default `true` local, `false` en Railway prod):
  corta antes de cargar el modelo y muestra una página 503 amable. El tab "Por
  selfie" se oculta en prod.

### Changed
- Búsqueda por selfie y `delete-my-data` pasados a **síncronos** (el prompt los
  hacía con tasks; cambiado por privacidad — la biometría nunca toca el broker).
- Campos nuevos en `Photo`: `needs_minor_review`, `has_faces_detected`, status
  `processing_failed` (`max_length` de status 16 → 24).

### Fixed
- **Bug de prod (cv2)**: el POST de selfie daba 500 en Railway (no en local) por
  `ImportError: libxcb.so.1` — InsightFace arrastra `opencv-python` (full) y su
  `cv2.so` necesita libs de sistema. Fix en `Dockerfile`: instalar
  `libgl1 libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6 libxrender1`. También se
  pre-cachea `buffalo_l` en build-time y gunicorn va con `--timeout 120`.
- **Bug de prod (RAM) — mitigado, no resuelto**: cargar `buffalo_l` necesita
  ~1.1 GB y el servicio web está capado a 1 GB → OOM (SIGKILL) → 502 que tiraba
  todo el sitio. Mitigación: el flag `FACE_SEARCH_ENABLED=false` en prod. Para
  reactivar: subir RAM a ≥2 GB, cambiar a `buffalo_s`, o microservicio aparte.

### Notes
- Deps nuevas: `insightface`, `onnxruntime`, `opencv-python-headless`. El modelo
  `buffalo_l` (~280 MB) se pre-cachea en build-time a `/opt/insightface`.
- 263 tests; ml/privacy/search 85–93%.

## [0.4.0] — Galería pública + búsqueda por dorsal (Fase 3)

### Added
- **Landing pública** (`/`) + **galería de evento** (`/eventos/<slug>/`) +
  **lightbox** (`/eventos/<slug>/foto/<id>/`), replicando las pantallas 1–6 del
  design system. Verificadas con screenshots en mobile y desktop.
- **Búsqueda por dorsal**: cache 5 min en Redis (IDs, no objetos), normalización
  + validación de formato, empty state con **sugerencias OCR** (variantes
  0/8/6/9, 1/7, 5/6/8 que existen en el evento).
- **Rate limiting** (ADR 0005): 60 búsquedas/h por IP, 10/día por (IP, evento,
  dorsal), 5 ZIPs/h por IP — con `django_ratelimit.core.is_ratelimited`.
  **No se creó modelo `SearchLog`** (sólo `Event.search_count` + Redis, por
  privacidad).
- **Descarga ZIP**: modelo `ZipDownload`, task `generate_zip` (baja originales de
  R2 → ZIP → sube a R2 → signed URL 1 h) + `cleanup_expired_zips` (beat cada
  hora). ZIP con originales full-res **sin watermark**.
- **Estados de retención aplicados**: `public`/`live`/`upcoming` → galería
  completa; `public_closed`/`searchable_only` → sólo búsqueda; `archived`/
  `pending_deletion` → 404 amigable; `private`/`draft`/`deleted` → 404.
- **SEO**: `sitemap.xml` (eventos públicos), `robots.txt`, OG tags en `base.html`.
- **Selección múltiple**: Alpine.js con `sessionStorage` por evento + bottom
  sheet de descarga con polling del estado del ZIP.

### Changed
- `Photo._presign` ahora usa R2 real (boto3 signed URL 15 min) en vez del stub
  `r2://`. Devuelve `""` si R2 no está configurado.

### Fixed
- Los comentarios `{# #}` multilínea de Django se renderizan como texto; se
  reemplazaron por `{% comment %}` (3 casos).

### Notes
- Cobertura global 85%. 215 tests.

## [0.3.0] — Upload fotógrafo + OCR (Fase 2)

### Added
- **Portal de fotógrafo** (`/u/<token>/`) sin cuenta, autenticado por token URL
  único. Se valida el hash sha256 en **cada** request (no se confía en sesiones).
  Se distinguen 410 (token muerto) vs 403 (límite de fotos).
- **Storage R2** (`apps/photos/storage.py`): wrapper boto3 con upload / signed
  URL (TTL 15 min) / delete / delete_many. Si `R2_ENDPOINT_URL` está vacío usa el
  default AWS (para tests con `moto`).
- **Imaging** (`apps/photos/imaging.py`): preview 1200px WebP q80 con watermark
  diagonal, thumbnail 400px WebP q75, extracción de EXIF.
- **OCR** (ADR 0004): PaddleOCR primario + EasyOCR fallback, heurística
  `is_bib_like` (1–6 chars, dígitos o letra+dígitos). Verificado E2E: 10/10
  dorsales sintéticos incl. alfanuméricos.
- **Celery**: `process_photo` (EXIF + preview + thumb → encadena OCR) +
  `run_ocr_on_photo`, con autoretry exponencial.

### Changed
- **`UploadView` es `csrf_exempt`**: el token URL es la autenticación; no hay
  sesión que CSRF defienda. La defensa real es el hash sha256 + el rate limit por
  token.

### Notes
- Deps nuevas: `paddleocr`, `paddlepaddle`, `easyocr` (runtime); `moto[s3]` (dev).
- **Pendiente prod**: crear servicios `worker` y `beat` en Railway. Hasta
  entonces las fotos suben pero quedan en `status=processing` sin procesar.

## [0.2.0] — Modelos + Admin (Fase 1)

### Added
- **Modelos**: `Event`, `Photo`, `Bib`, `FaceEmbedding`, `PhotographerLink`,
  `AuditLog`, `DataDeletionRequest`, `UserMFA` (stub TOTP), y `User(AbstractUser)`
  custom (`AUTH_USER_MODEL = 'core.User'`).
- **Política de retención escalonada de eventos** (§3 de `CLAUDE.md`): 4 ventanas
  temporales + el flag `permanent_archive`. `Event` extendido con 8 estados, 3
  visibilidades, fechas de retención (`public_until`, `searchable_until`,
  `archive_until`) y counters denormalizados.
- **Django admin custom** con `django-unfold` (ADR 0002), paleta del design
  system (dark theme).
- **`EncryptedCharField`** custom en `apps/core/fields.py` usando
  `cryptography.fernet` (sin dep nueva — `cryptography` ya entra como transitiva).
- Factories + fixtures para tests, comando `seed_data` para data de prueba,
  tests de modelos.

### Notes
- Postgres: dev pg16 / prod pg18 (decisión documentada en `CLAUDE.md` §2).
  pgvector ≥ 0.7 corre en ambos.

## [0.1.0] — Setup (Fase 0)

### Added
- Estructura del proyecto Django con `apps/`, settings divididos
  (`base` / `dev` / `prod`).
- `pyproject.toml` con `ruff`, `black`, `mypy` (+ `django-stubs`), `pytest`.
- Pre-commit hooks (`ruff` + `black` + `mypy`).
- GitHub Actions con CI básico (lint + types + tests).
- `docker-compose.yml` para Postgres (pgvector) + Redis + web + worker + beat.
- `Dockerfile` multi-stage (Tailwind + Python + runtime) y `railway.toml`.
- Health check `/healthz`.
- README con instrucciones de setup local.

[1.0.0]: #100--production-ready-fase-7--en-progreso-pendiente-de-tag-pendiente
[0.7.0]: #070--privacidad--retención--hardening-fase-6
[0.6.0]: #060--dashboard-admin--cola-de-aprobación-fase-5
[0.5.0]: #050--búsqueda-por-selfie--reconocimiento-facial-fase-4
[0.4.0]: #040--galería-pública--búsqueda-por-dorsal-fase-3
[0.3.0]: #030--upload-fotógrafo--ocr-fase-2
[0.2.0]: #020--modelos--admin-fase-1
[0.1.0]: #010--setup-fase-0

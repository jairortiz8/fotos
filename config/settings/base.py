"""Settings base — compartidos entre dev y prod.

Estos NO se usan directamente. Importá `config.settings.dev` o
`config.settings.prod` vía la env var DJANGO_SETTINGS_MODULE.
"""

from __future__ import annotations

from pathlib import Path

import environ
from celery.schedules import crontab

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ----------------------------------------------------------------------------
# Env vars
# ----------------------------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECRET_KEY=(str, "insecure-default-change-me"),
    DATABASE_URL=(str, "postgres://runfoto:runfoto@localhost:5432/runfoto"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    CELERY_BROKER_URL=(str, "redis://localhost:6379/1"),
    CELERY_RESULT_BACKEND=(str, "redis://localhost:6379/2"),
    SITE_NAME=(str, "find your foto"),
    SITE_DOMAIN=(str, "localhost:8000"),
    SITE_INSTAGRAM=(str, "findyourfoto"),
    SENTRY_DSN=(str, ""),
    SENTRY_ENVIRONMENT=(str, "development"),
    SENTRY_TRACES_SAMPLE_RATE=(float, 0.0),
    LOG_LEVEL=(str, "INFO"),
    GIT_SHA=(str, "unknown"),
    NOTIFIER_BACKEND=(str, "whatsapp_manual"),
    LANGUAGE_CODE=(str, "es"),
    TIME_ZONE=(str, "America/El_Salvador"),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    DEFAULT_FROM_EMAIL=(str, "noreply@runfoto.local"),
    # R2 (Fase 2+)
    R2_ACCESS_KEY_ID=(str, ""),
    R2_SECRET_ACCESS_KEY=(str, ""),
    R2_BUCKET_NAME=(str, ""),
    R2_ENDPOINT_URL=(str, ""),
    R2_PUBLIC_BASE_URL=(str, ""),
    # Upload limits (Fase 2). 40 MB: las fotos pro de alta resolución (Canon R,
    # 45MP) pesan 20-30 MB → con 15 MB fallaban por tamaño.
    PHOTO_UPLOAD_MAX_MB=(int, 40),
    # Búsqueda por selfie (Fase 4). El modelo buffalo_l necesita >1GB de RAM
    # al cargar. En el dyno de prod (capado a 1GB) se deshabilita poniendo esto
    # en False hasta subir la RAM o cambiar de modelo (decisión pendiente).
    # Local/dev queda en True (la RAM alcanza).
    FACE_SEARCH_ENABLED=(bool, True),
)

# .env si existe
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# ----------------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# ----------------------------------------------------------------------------
# Branding
# ----------------------------------------------------------------------------
SITE_NAME = env("SITE_NAME")
SITE_DOMAIN = env("SITE_DOMAIN")
# Usuario de Instagram del sitio (sin @). Vacío = no se muestra en el footer.
SITE_INSTAGRAM = env("SITE_INSTAGRAM").lstrip("@").strip()

# Búsqueda por selfie / borrado por selfie (Fase 4). Ver nota en env() arriba.
FACE_SEARCH_ENABLED = env("FACE_SEARCH_ENABLED")

# Procesamiento facial en el UPLOAD (extracción de embeddings + blur de menores
# en el worker de Celery). Por defecto SIGUE a FACE_SEARCH_ENABLED: si la
# búsqueda por selfie está apagada (prod), el worker tampoco corre el modelo
# facial — así no carga InsightFace (~1 GB en RAM) y el procesamiento queda
# liviano y barato (solo preview/thumbnail + OCR de dorsal). Se puede setear
# aparte si algún día se quiere extraer embeddings sin exponer la búsqueda.
FACE_PROCESSING_ENABLED = env.bool("FACE_PROCESSING_ENABLED", default=FACE_SEARCH_ENABLED)

# OCR exhaustivo automático en cada subida (pedido de Jair: el OCR normal
# perdía dorsales y le tocaba cargarlos a mano). Corre ambos engines + pasadas
# extra (copia agrandada en fotos chicas / cuadrantes en fotos de cámara).
# Más lento por foto (~15-20s vs ~5s) pero el preview va por otra task → las
# fotos quedan aprobables igual de rápido; sólo el dorsal completo tarda más.
# Apagable por env si algún día el ruido extra molesta más de lo que aporta.
OCR_EXHAUSTIVE_ON_UPLOAD = env.bool("OCR_EXHAUSTIVE_ON_UPLOAD", default=True)

# Blur automático de caras de menores en el preview público (parte del paso
# facial). Decisión de Jair: APAGADO en prod (MINOR_BLUR_ENABLED=false) — quiere
# que el blur nunca aparezca. El indexado de embeddings (búsqueda por selfie)
# sigue funcionando; sólo se saltea la regeneración con blur. Default True para
# local/tests (mantiene la cobertura de la lógica de blur de Fase 4).
MINOR_BLUR_ENABLED = env.bool("MINOR_BLUR_ENABLED", default=True)

# ----------------------------------------------------------------------------
# Apps
# ----------------------------------------------------------------------------
DJANGO_APPS = [
    # django-unfold REEMPLAZA el admin default. DEBE ir antes que `django.contrib.admin`.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "django_htmx",
    "csp",  # Content Security Policy (Fase 6)
    "tailwind",
    # "theme" se agrega después de `python manage.py tailwind init theme`.
    "theme",
]

LOCAL_APPS = [
    "apps.core",
    "apps.events",
    "apps.photos",
    "apps.photographers",
    "apps.search",
    "apps.downloads",
    "apps.ml",
    "apps.notifications",
    "apps.privacy",
    "apps.dashboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ----------------------------------------------------------------------------
# Middleware
# ----------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "csp.middleware.CSPMiddleware",
]

# ----------------------------------------------------------------------------
# Content Security Policy (django-csp 4.x). Ajustada a lo que RunFoto usa de
# verdad (NO Google Fonts — auto-hospedamos). 'unsafe-inline' en script/style
# es necesario por las directivas inline de Alpine.js y estilos puntuales.
# ----------------------------------------------------------------------------
# NOTA sobre script-src:
#   - 'unsafe-eval' es OBLIGATORIO para Alpine.js: su build estándar (cdn.min.js)
#     evalúa las expresiones de los directivos (x-data, x-show, @click, ...) con
#     `new Function()`. Sin 'unsafe-eval' el navegador real bloquea TODA la
#     interactividad de Alpine (multi-select, bottom sheet de descarga, menú y
#     drawer del dashboard, navegación del lightbox). Verificado en navegador.
#     Alternativa más estricta a futuro: migrar al build @alpinejs/csp (sin eval)
#     reescribiendo las expresiones inline como componentes Alpine.data(). Ver
#     docs/adr/0009-security-headers.md.
#   - 'unsafe-inline' cubre los pocos <script> inline y los handlers; junto con
#     'unsafe-eval' es el perfil habitual de un sitio HTMX + Alpine + Tailwind.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'", "https://unpkg.com"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "font-src": ["'self'"],
        "img-src": ["'self'", "data:", "https://*.r2.cloudflarestorage.com"],
        "connect-src": ["'self'", "https://*.ingest.sentry.io", "https://*.ingest.us.sentry.io"],
        "frame-ancestors": ["'none'"],
        "form-action": ["'self'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
    }
}

# ----------------------------------------------------------------------------
# URL / WSGI / ASGI
# ----------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ----------------------------------------------------------------------------
# Templates
# ----------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

# ----------------------------------------------------------------------------
# Database (Postgres + pgvector)
# ----------------------------------------------------------------------------
DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": 60,  # connection pooling Django-builtin
    }
}

# ----------------------------------------------------------------------------
# Cache (Redis)
# ----------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "TIMEOUT": 300,
    }
}

# ----------------------------------------------------------------------------
# Celery
# ----------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = env("TIME_ZONE")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30  # 30 min

# Routing de tasks a colas (3 colas). El reconocimiento facial es LENTO (~15s/
# foto con InsightFace) y, en un solo worker, tapa la cola: los `process_photo`
# (preview/thumbnail, ~2s → deja la foto lista para aprobar) quedan atrás y la
# foto se ve "procesando" un buen rato. Separamos:
#   - cola `fast`   → process_photo + OCR (rápido, NO carga el modelo facial).
#                     La consume EXCLUSIVAMENTE el worker liviano (worker_fast).
#   - cola `faces`  → SOLO la cara (worker pesado, con InsightFace).
#   - cola `celery` → crons (beat) + cualquier task sin ruta explícita.
# Clave: worker_fast escucha SOLO `fast`, así NUNCA agarra una task de cara (si
# escuchara `celery` agarraría las de cara viejas encoladas antes del routing y
# se quedaría sin RAM cargando el modelo). El worker pesado escucha las 3.
CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_ROUTES = {
    "photos.process_photo": {"queue": "fast"},
    "photos.run_ocr_on_photo": {"queue": "fast"},
    "photos.run_face_recognition_on_photo": {"queue": "faces"},
}

CELERY_BEAT_SCHEDULE: dict[str, dict] = {
    # Retención escalonada de eventos: avanza estados según fechas (Fase 6).
    "enforce-event-retention": {
        "task": "privacy.enforce_event_retention_policy",
        "schedule": crontab(hour=2, minute=0),  # 2 AM diario
    },
    # Borra embeddings faciales inactivos > 90 días (Fase 4).
    "cleanup-old-embeddings": {
        "task": "privacy.cleanup_old_embeddings",
        "schedule": crontab(hour=3, minute=0),  # 3 AM diario
    },
    # Marca inactivos los links de fotógrafo vencidos (Fase 6).
    "cleanup-expired-links": {
        "task": "privacy.cleanup_expired_photographer_links",
        "schedule": crontab(hour=4, minute=0),  # 4 AM diario
    },
    # Marca failed las fotos atascadas en uploading/processing > 1h (Fase 6).
    "cleanup-stuck-photos": {
        "task": "privacy.cleanup_failed_processing",
        "schedule": crontab(minute=0, hour="*/6"),  # cada 6 horas
    },
    # Re-encola el indexado facial de fotos aprobadas recientes sin caras
    # (recupera lo perdido por OOM/fallos → la búsqueda por selfie queda completa).
    "reindex-missing-faces": {
        "task": "photos.reindex_missing_faces",
        "schedule": crontab(minute=30, hour="*/3"),  # cada 3 horas
    },
    # Borra ZIPs expirados de R2 (Fase 3).
    "cleanup-expired-zips": {
        "task": "downloads.cleanup_expired_zips",
        "schedule": crontab(minute=15),  # cada hora :15
    },
    # Detecta objetos huérfanos en R2 (Fase 6).
    "cleanup-orphaned-r2": {
        "task": "privacy.cleanup_orphaned_r2_objects",
        "schedule": crontab(hour=5, minute=0, day_of_week=0),  # Domingo 5 AM
    },
    # Backup de la DB a R2 (Fase 6).
    "backup-database": {
        "task": "core.backup_database",
        "schedule": crontab(hour=1, minute=0),  # 1 AM diario
    },
    # Borra audit logs > 2 años (Fase 6).
    "cleanup-old-audit-logs": {
        "task": "privacy.cleanup_old_audit_logs",
        "schedule": crontab(hour=6, minute=0, day_of_month=1),  # día 1 del mes, 6 AM
    },
}

# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sesiones de admin: 12 horas, sin "remember me" largo.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
# Extender la sesión en cada request (12h desde la última actividad, no desde login).
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_HTTPONLY = True

# Dashboard admin (Fase 5). El login custom vive en /dashboard/login/; el Django
# admin (django-unfold) queda como fallback de emergencia en /admin/django/.
LOGIN_URL = "dashboard:dashboard_login"
LOGIN_REDIRECT_URL = "dashboard:dashboard_home"
LOGOUT_REDIRECT_URL = "core:index"

# ----------------------------------------------------------------------------
# i18n / l10n
# ----------------------------------------------------------------------------
LANGUAGE_CODE = env("LANGUAGE_CODE")
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

# Solo español activo. "en" queda como placeholder para futuro.
LANGUAGES = [
    ("es", "Español"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

# ----------------------------------------------------------------------------
# Static / media
# ----------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# WhiteNoise: en prod usamos manifest + compressed (override en prod.py)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ----------------------------------------------------------------------------
# Defaults
# ----------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ----------------------------------------------------------------------------
# Auth — User custom desde Fase 1.
# ----------------------------------------------------------------------------
AUTH_USER_MODEL = "core.User"

# ----------------------------------------------------------------------------
# Django Admin custom (django-unfold) — ADR 0002.
# Paleta replica reference/runfoto-design/index.html (dark theme).
# ----------------------------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": SITE_NAME,
    "SITE_HEADER": SITE_NAME,
    "SITE_SUBHEADER": "Admin",
    "SITE_SYMBOL": "photo_camera",  # material symbol
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "ENVIRONMENT": "config.settings.unfold_environment",
    "BORDER_RADIUS": "8px",
    "COLORS": {
        # Base (background + surfaces del design system)
        "base": {
            "50": "250 250 250",  # text-1 invertido
            "100": "229 229 234",
            "200": "199 199 204",
            "300": "161 161 166",  # text-2
            "400": "107 107 112",  # text-3
            "500": "63 63 70",
            "600": "42 42 46",  # border
            "700": "31 31 35",  # surface-2
            "800": "23 23 26",  # surface
            "900": "10 10 11",  # bg
            "950": "0 0 0",
        },
        # Primary = naranja brand (FC5200)
        "primary": {
            "50": "255 240 230",
            "100": "255 219 199",
            "200": "255 188 153",
            "300": "255 156 105",
            "400": "255 122 58",
            "500": "252 82 0",  # base brand
            "600": "227 73 0",
            "700": "189 61 0",
            "800": "151 49 0",
            "900": "115 36 0",
            "950": "78 24 0",
        },
        # Font hierarchy
        "font": {
            "subtle-light": "var(--color-base-500)",
            "subtle-dark": "var(--color-base-400)",
            "default-light": "var(--color-base-600)",
            "default-dark": "var(--color-base-300)",
            "important-light": "var(--color-base-900)",
            "important-dark": "var(--color-base-100)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Contenido",
                "separator": True,
                "items": [
                    {
                        "title": "Eventos",
                        "icon": "event",
                        "link": "/admin/django/events/event/",
                    },
                    {
                        "title": "Fotos",
                        "icon": "photo_library",
                        "link": "/admin/django/photos/photo/",
                    },
                    {
                        "title": "Dorsales",
                        "icon": "tag",
                        "link": "/admin/django/photos/bib/",
                    },
                ],
            },
            {
                "title": "Operación",
                "separator": True,
                "items": [
                    {
                        "title": "Fotógrafos",
                        "icon": "camera",
                        "link": "/admin/django/photographers/photographerlink/",
                    },
                ],
            },
            {
                "title": "Privacidad",
                "separator": True,
                "items": [
                    {
                        "title": "Solicitudes de borrado",
                        "icon": "delete_forever",
                        "link": "/admin/django/privacy/datadeletionrequest/",
                    },
                ],
            },
            {
                "title": "Sistema",
                "separator": True,
                "items": [
                    {
                        "title": "Auditoría",
                        "icon": "history",
                        "link": "/admin/django/core/auditlog/",
                    },
                    {
                        "title": "Usuarios",
                        "icon": "people",
                        "link": "/admin/django/core/user/",
                    },
                ],
            },
        ],
    },
}

# ----------------------------------------------------------------------------
# Tailwind (django-tailwind)
# ----------------------------------------------------------------------------
TAILWIND_APP_NAME = "theme"

# ----------------------------------------------------------------------------
# Email
# ----------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")

# ----------------------------------------------------------------------------
# RunFoto-specific
# ----------------------------------------------------------------------------
NOTIFIER_BACKEND = env("NOTIFIER_BACKEND")

# Cloudflare R2 (S3-compatible) — vacío hasta Fase 2.
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = env("R2_BUCKET_NAME")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL")
R2_PUBLIC_BASE_URL = env("R2_PUBLIC_BASE_URL")

# Tamaño máximo de upload del fotógrafo (bytes).
PHOTO_UPLOAD_MAX_BYTES = env("PHOTO_UPLOAD_MAX_MB") * 1024 * 1024

# ----------------------------------------------------------------------------
# Logging — JSON-ish para Sentry / Railway
# ----------------------------------------------------------------------------
# En prod usamos logs JSON (fáciles de parsear/filtrar en Railway); en dev,
# texto legible. GIT_SHA y release se exponen para correlacionar con Sentry.
GIT_SHA = env("GIT_SHA")
LOG_LEVEL = env("LOG_LEVEL")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if DEBUG else "json",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

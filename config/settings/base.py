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
    SITE_NAME=(str, "RunFoto"),
    SITE_DOMAIN=(str, "localhost:8000"),
    SENTRY_DSN=(str, ""),
    SENTRY_ENVIRONMENT=(str, "development"),
    SENTRY_TRACES_SAMPLE_RATE=(float, 0.0),
    NOTIFIER_BACKEND=(str, "whatsapp_manual"),
    LANGUAGE_CODE=(str, "es"),
    TIME_ZONE=(str, "America/Guatemala"),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    DEFAULT_FROM_EMAIL=(str, "noreply@runfoto.local"),
    # R2 (Fase 2+)
    R2_ACCESS_KEY_ID=(str, ""),
    R2_SECRET_ACCESS_KEY=(str, ""),
    R2_BUCKET_NAME=(str, ""),
    R2_ENDPOINT_URL=(str, ""),
    R2_PUBLIC_BASE_URL=(str, ""),
    # Upload limits (Fase 2)
    PHOTO_UPLOAD_MAX_MB=(int, 15),
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

# Búsqueda por selfie / borrado por selfie (Fase 4). Ver nota en env() arriba.
FACE_SEARCH_ENABLED = env("FACE_SEARCH_ENABLED")

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
]

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
CELERY_BEAT_SCHEDULE: dict[str, dict] = {
    # Borra ZIPs expirados de R2 cada hora (Fase 3).
    "cleanup-expired-zips": {
        "task": "downloads.cleanup_expired_zips",
        "schedule": 60 * 60,  # cada hora
    },
    # Borra embeddings faciales inactivos > 90 días, diario a las 3 AM (Fase 4).
    "cleanup-old-embeddings": {
        "task": "privacy.cleanup_old_embeddings",
        "schedule": crontab(hour=3, minute=0),
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
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

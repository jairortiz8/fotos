"""Settings de desarrollo local."""

from __future__ import annotations

from .base import *
from .base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True

# debug toolbar
INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    *MIDDLEWARE,
]

INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Cookies inseguras OK en dev.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Email a consola.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# django-tailwind: descubrir npm automáticamente.
INTERNAL_IPS_DEBUG_TOOLBAR = INTERNAL_IPS

# Cache local más permisivo (no expira en dev para iterar rápido)
# CACHES heredado de base.

"""Settings de producción (Railway)."""

from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *
from .base import STORAGES, env

DEBUG = False

# ----------------------------------------------------------------------------
# Security (HTTPS only)
# ----------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# El healthcheck interno de Railway pega por HTTP sin X-Forwarded-Proto;
# si dejamos que SECURE_SSL_REDIRECT lo agarre, devuelve 301 y nunca llega
# a la vista. Eximimos `/healthz` (y solo `/healthz`) del redirect HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = 31_536_000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"

# ----------------------------------------------------------------------------
# WhiteNoise: compressed + manifest para cache-busting agresivo
# ----------------------------------------------------------------------------
STORAGES = {
    **STORAGES,
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ----------------------------------------------------------------------------
# Sentry (solo si hay DSN configurado)
# ----------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        send_default_pii=False,  # nunca enviar PII; CLAUDE.md §3 privacidad
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
    )

# ----------------------------------------------------------------------------
# Content Security Policy (placeholder — se endurece en Fase 6)
# ----------------------------------------------------------------------------
# Nota: hoy NO usamos django-csp (ahorrar dep en Fase 0). Cuando lo activemos
# en Fase 6, agregar 'csp.middleware.CSPMiddleware' al MIDDLEWARE y configurar
# las directivas acá.

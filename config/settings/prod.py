"""Settings de producción (Railway)."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from .base import *
from .base import GIT_SHA, STORAGES, env

DEBUG = False


def filter_sensitive_data(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Última línea de defensa: limpia datos sensibles antes de mandar a Sentry.

    NUNCA debe salir un embedding, token o selfie. Idealmente nunca llega acá
    (no metemos PII en excepciones), pero por las dudas filtramos.
    """
    request = event.get("request")
    if isinstance(request, dict) and request.get("data"):
        request["data"] = "[FILTERED]"

    exception = event.get("exception")
    if isinstance(exception, dict):
        for value in exception.get("values", []):
            for frame in value.get("stacktrace", {}).get("frames", []):
                vars_ = frame.get("vars", {})
                for key in list(vars_.keys()):
                    if any(s in key.lower() for s in ("embedding", "token", "selfie", "password")):
                        vars_[key] = "[FILTERED]"
    return event


# ----------------------------------------------------------------------------
# Security (HTTPS only)
# ----------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# El healthcheck interno de Railway pega por HTTP sin X-Forwarded-Proto;
# si dejamos que SECURE_SSL_REDIRECT lo agarre, devuelve 301 y nunca llega
# a la vista. Eximimos `/healthz` (y solo `/healthz`) del redirect HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^healthz"]  # cubre /healthz y /healthz/lite
SECURE_HSTS_SECONDS = 31_536_000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True  # legacy header X-XSS-Protection (defensa en profundidad)
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
        release=GIT_SHA,
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        profiles_sample_rate=0.0,
        send_default_pii=False,  # nunca enviar PII; CLAUDE.md §3 privacidad
        before_send=filter_sensitive_data,  # type: ignore[arg-type]
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
    )

# ----------------------------------------------------------------------------
# Content Security Policy
# ----------------------------------------------------------------------------
# La CSP (django-csp 4.x) está en `base.py` → aplica en dev y prod por igual.
# Acá no hace falta nada extra; el middleware ya está en MIDDLEWARE.

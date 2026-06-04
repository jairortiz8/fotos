"""Tests de headers de seguridad y CSP (Fase 6)."""

from __future__ import annotations

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
def test_csp_header_present_with_directives(client: Client) -> None:
    """La CSP vive en base.py → aplica siempre. Verificamos las directivas clave."""
    resp = client.get("/healthz")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "https://unpkg.com" in csp  # HTMX/Alpine
    # Alpine.js evalúa sus directivas con new Function() → REQUIERE 'unsafe-eval'.
    # Sin esto, toda la interactividad de Alpine se rompe en el navegador real
    # (verificado en Fase 6). NO quitar sin migrar a @alpinejs/csp. Ver ADR 0009.
    assert "'unsafe-eval'" in csp
    assert "data:" in csp  # QR inline
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.django_db
def test_x_frame_options_deny(client: Client) -> None:
    resp = client.get("/healthz")
    assert resp.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.django_db
@override_settings(
    SECURE_HSTS_SECONDS=31_536_000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
)
def test_hsts_header_when_secure(client: Client) -> None:
    resp = client.get("/healthz", secure=True)
    hsts = resp.headers.get("Strict-Transport-Security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts


def test_prod_cookie_and_referrer_settings() -> None:
    """Verifica los settings de seguridad del módulo de producción."""
    import config.settings.prod as prod

    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_SAMESITE == "Strict"
    assert prod.CSRF_COOKIE_SAMESITE == "Strict"
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS == 31_536_000
    assert prod.X_FRAME_OPTIONS == "DENY"

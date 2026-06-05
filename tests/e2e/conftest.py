"""Fixtures para los tests E2E (Playwright + live_server de Django).

Los E2E manejan un navegador real (Chromium headless) contra un servidor Django
vivo. Son pesados, por eso:
- van marcados `@pytest.mark.e2e` y corren en su propio job de CI;
- si Playwright no está instalado (el job de tests normal), no se colectan.
"""

from __future__ import annotations

import os

# Playwright (API sync) corre en un event loop de greenlets; Django lo detecta
# como "contexto async" y bloquea las operaciones de DB sync (falso positivo,
# no es DB async real). Esta env var es el workaround documentado para E2E.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

import pytest

try:
    import playwright  # noqa: F401

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAS_PLAYWRIGHT = False

# Sin Playwright instalado, ignoramos los módulos E2E para no romper la colecta.
collect_ignore_glob: list[str] = [] if _HAS_PLAYWRIGHT else ["test_*.py"]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):  # type: ignore[no-untyped-def]
    """Viewport mobile-first + locale español para todos los contextos."""
    return {
        **browser_context_args,
        "viewport": {"width": 390, "height": 844},
        "locale": "es-ES",
    }


@pytest.fixture(autouse=True)
def _locmem_cache(settings):  # type: ignore[no-untyped-def]
    """Cache en memoria para el servidor de prueba (rate limiting determinístico)."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.RATELIMIT_USE_CACHE = "default"

"""Pytest fixtures comunes para RunFoto.

Convenciones:
- Tests usan `@pytest.mark.django_db` para acceder a la DB.
- `client` viene de pytest-django (Django test client).
- `settings` viene de pytest-django y permite override en runtime.
"""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def client() -> Client:
    """Cliente HTTP de Django para tests."""
    return Client()


@pytest.fixture
def site_name(settings) -> str:  # type: ignore[no-untyped-def]
    """Atajo: nombre del site según settings (puede cambiar via env)."""
    return settings.SITE_NAME

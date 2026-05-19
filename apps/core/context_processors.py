"""Context processors comunes para todos los templates."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def site(request: HttpRequest) -> dict[str, str]:
    """Inyecta `site_name` y `site_domain` en cada template.

    El nombre del proyecto NO se hardcodea en HTML — siempre via
    `{{ site_name }}` para permitir rebrand sin cambios de código.
    """
    return {
        "site_name": settings.SITE_NAME,
        "site_domain": settings.SITE_DOMAIN,
    }

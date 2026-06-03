"""Context processors comunes para todos los templates."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def site(request: HttpRequest) -> dict[str, str | bool]:
    """Inyecta `site_name`, `site_domain` y `face_search_enabled` en cada template.

    El nombre del proyecto NO se hardcodea en HTML — siempre via
    `{{ site_name }}` para permitir rebrand sin cambios de código.

    `face_search_enabled` controla si se muestra el tab "Por selfie" (Fase 4):
    en prod está apagado hasta resolver la RAM del modelo buffalo_l.
    """
    return {
        "site_name": settings.SITE_NAME,
        "site_domain": settings.SITE_DOMAIN,
        "face_search_enabled": settings.FACE_SEARCH_ENABLED,
    }

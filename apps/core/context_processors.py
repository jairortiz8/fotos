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
    # Para el wordmark en dos tonos separamos la última palabra del resto
    # ("find your foto" → "find your" + "foto"). Derivado de site_name para no
    # hardcodear el nombre. Nombre de una sola palabra → prefix vacío.
    name: str = settings.SITE_NAME
    prefix, _, last = name.rpartition(" ")
    instagram: str = settings.SITE_INSTAGRAM
    return {
        "site_name": name,
        "site_name_prefix": prefix,
        "site_name_last": last or name,
        "site_domain": settings.SITE_DOMAIN,
        "face_search_enabled": settings.FACE_SEARCH_ENABLED,
        "site_instagram": instagram,
        "site_instagram_url": f"https://instagram.com/{instagram}" if instagram else "",
    }

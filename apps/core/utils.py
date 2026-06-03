"""Utilidades compartidas: IP, hashing, validación de dorsales, rate limiting.

Centralizadas acá para que `photographers`, `events`, `photos` y `downloads`
las reusen sin duplicar.
"""

from __future__ import annotations

import hashlib
import re

from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited


# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------
def get_client_ip(request: HttpRequest) -> str | None:
    """IP del cliente respetando X-Forwarded-For (Railway está detrás de proxy)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def hash_ip(ip: str | None) -> str:
    """sha256 de la IP para rate-limiting / logging sin guardar la IP cruda."""
    return hashlib.sha256((ip or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Bib (dorsal) format
# ---------------------------------------------------------------------------
_BIB_RE = re.compile(r"^(?:\d{1,6}|[A-Z]\d{1,5})$")


def normalize_bib_query(raw: str) -> str:
    """Normaliza un query de dorsal: trim + upper."""
    return raw.strip().upper()


def is_valid_bib_format(value: str) -> bool:
    """¿El string tiene forma de dorsal? 1-6 dígitos, o letra + 1-5 dígitos."""
    return bool(_BIB_RE.match(normalize_bib_query(value)))


# ---------------------------------------------------------------------------
# OCR variants — para sugerencias cuando una búsqueda da 0 resultados.
#
# OCR confunde caracteres visualmente similares. Generamos las variantes
# plausibles de un número para sugerir dorsales que SÍ existen en el evento.
# ---------------------------------------------------------------------------
_OCR_CONFUSIONS: dict[str, list[str]] = {
    "0": ["8", "6", "9"],
    "1": ["7"],
    "3": ["8"],
    "5": ["6", "8"],
    "6": ["5", "8", "0"],
    "7": ["1"],
    "8": ["0", "3", "6", "9"],
    "9": ["8", "0"],
}


def generate_ocr_variants(query: str, *, max_variants: int = 40) -> list[str]:
    """Genera variantes del número cambiando un dígito por uno OCR-confundible.

    Sólo aplica a queries puramente numéricos. Devuelve hasta `max_variants`,
    sin incluir el query original.
    """
    if not query.isdigit():
        return []

    variants: list[str] = []
    seen: set[str] = {query}
    for i, ch in enumerate(query):
        for alt in _OCR_CONFUSIONS.get(ch, []):
            candidate = query[:i] + alt + query[i + 1 :]
            if candidate not in seen:
                seen.add(candidate)
                variants.append(candidate)
                if len(variants) >= max_variants:
                    return variants
    return variants


# ---------------------------------------------------------------------------
# Rate limiting (Redis-backed via django-ratelimit)
#
# Usamos la API programática `is_ratelimited` para tener control fino dentro
# de las vistas (la galería sin búsqueda no debe rate-limitear).
# ---------------------------------------------------------------------------
def check_general_search_rate_limit(request: HttpRequest) -> bool:
    """60 búsquedas/hora por IP. Devuelve True si está PERMITIDO."""
    limited = is_ratelimited(
        request,
        group="search-general",
        key="ip",
        rate="60/h",
        method=("GET",),
        increment=True,
    )
    return not limited


def check_bib_specific_rate_limit(request: HttpRequest, event_id: int, bib: str) -> bool:
    """10 búsquedas/día por (IP, evento, dorsal). Devuelve True si PERMITIDO."""

    def _key(group: str, req: HttpRequest) -> str:
        return f"{get_client_ip(req)}:{event_id}:{bib}"

    limited = is_ratelimited(
        request,
        group="search-bib",
        key=_key,
        rate="10/d",
        method=("GET",),
        increment=True,
    )
    return not limited


def check_zip_rate_limit(request: HttpRequest) -> bool:
    """5 ZIPs/hora por IP. Devuelve True si está PERMITIDO."""
    limited = is_ratelimited(
        request,
        group="zip-download",
        key="ip",
        rate="5/h",
        method=("POST",),
        increment=True,
    )
    return not limited

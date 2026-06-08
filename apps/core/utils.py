"""Utilidades compartidas: IP, hashing, validación de dorsales, rate limiting.

Centralizadas acá para que `photographers`, `events`, `photos` y `downloads`
las reusen sin duplicar.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re

from django.http import HttpRequest
from django.utils import timezone
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


def anonymize_ip(ip_str: str | None) -> str | None:
    """Anonimiza una IP truncándola (la guardamos parcial, no cruda).

    IPv4: pone en 0 el último octeto       1.2.3.4    → 1.2.3.0
    IPv6: pone en 0 los últimos 80 bits    2001:db8::1 → 2001:db8::
    Devuelve None si el input no es una IP válida.
    """
    if not ip_str:
        return None
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv4Address):
        return str(ipaddress.IPv4Address(ip.packed[:3] + b"\x00"))
    return str(ipaddress.IPv6Address(ip.packed[:6] + b"\x00" * 10))


def hash_ip(ip: str | None, salt: str | None = None) -> str:
    """sha256 de la IP para rate-limiting / logging sin guardar la IP cruda.

    Usa una salt DIARIA por default (fecha UTC): el hash de una misma IP cambia
    cada día, así no se puede correlacionar la actividad de una IP a lo largo del
    tiempo ni hacer reverse-lookup con un diccionario de IPs.
    """
    if salt is None:
        salt = timezone.now().strftime("%Y-%m-%d")
    return hashlib.sha256(f"{ip or ''}:{salt}".encode()).hexdigest()


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


def check_photo_download_rate_limit(request: HttpRequest) -> bool:
    """200 descargas de foto/hora por IP. Generoso (un corredor baja varias de a
    una), pero frena el scrapeo de un evento entero por el proxy. True = permitido."""
    limited = is_ratelimited(
        request,
        group="photo-download",
        key="ip",
        rate="200/h",
        method=("GET",),
        increment=True,
    )
    return not limited


def check_selfie_rate_limit(request: HttpRequest) -> bool:
    """20 búsquedas por selfie/hora por IP (más caro computacionalmente)."""
    limited = is_ratelimited(
        request,
        group="selfie-search",
        key="ip",
        rate="20/h",
        method=("POST",),
        increment=True,
    )
    return not limited


def check_deletion_rate_limit(request: HttpRequest) -> bool:
    """5 solicitudes de borrado/hora por IP (operación seria)."""
    limited = is_ratelimited(
        request,
        group="data-deletion",
        key="ip",
        rate="5/h",
        method=("POST",),
        increment=True,
    )
    return not limited

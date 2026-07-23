"""Render LIMPIO (sin logos) del área de invitados, cacheado en R2.

Rendimiento: el grid del invitado sirve las miniaturas limpias **directamente
desde R2** (URL firmada puesta en el `<img src>`), igual que la galería pública
sirve sus thumbnails. Así el navegador baja las 60 fotos de la página directo de
R2 en paralelo, sin pasar por Django foto por foto (antes cada miniatura era un
request a Django con HEAD a R2 + generación on-demand + redirect 302 — lento).

Las versiones limpias se generan una sola vez y quedan cacheadas en R2 bajo
`reviewer_clean/<slug>/<id>_<size>.webp`. `warm_event_clean_renders` las
pre-genera (idempotente). Si alguna falta, el grid cae al render on-demand
(`ReviewerCleanImageView`), que la genera y la deja cacheada para la próxima.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from io import BytesIO

from django.core.cache import cache
from django.urls import reverse

from apps.events.models import Event
from apps.photos.imaging import REVIEWER_CLEAN_SIZES, generate_clean_render
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage

logger = logging.getLogger(__name__)

CLEAN_PREFIX = "reviewer_clean"
_EXISTING_KEYS_TTL = 300  # 5 min — cachea qué renders limpios ya existen
_SIGNED_URL_TTL = 3600  # 1 h — dura toda una sesión de navegación


def clean_key(event_slug: str, photo_id: int, size: str) -> str:
    """Key en R2 de la versión limpia de una foto a un tamaño dado."""
    return f"{CLEAN_PREFIX}/{event_slug}/{photo_id}_{size}.webp"


def _existing_clean_keys(event: Event) -> set[str]:
    """Set (cacheado 5 min) de keys limpias ya generadas para el evento.

    Un solo LIST a R2 por evento cada 5 min, en vez de un HEAD por foto por
    request. Si R2 no está configurado (tests sin credenciales), devuelve vacío.
    """
    cache_k = f"rvclean_keys:{event.slug}"
    cached = cache.get(cache_k)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    try:
        keys = set(default_storage().list_keys(f"{CLEAN_PREFIX}/{event.slug}/"))
    except (R2NotConfiguredError, R2UploadError):
        keys = set()
    cache.set(cache_k, keys, _EXISTING_KEYS_TTL)
    return keys


def invalidate_existing_keys(event_slug: str) -> None:
    """Olvida el set cacheado (llamar tras generar renders nuevos)."""
    cache.delete(f"rvclean_keys:{event_slug}")


def attach_clean_thumb_urls(photos: Iterable[Photo], event: Event) -> None:
    """Setea `photo.clean_thumb_url` en cada foto del grid.

    URL firmada directa de R2 si la miniatura limpia ya existe (rápido, el
    navegador baja directo de R2); si no, la ruta on-demand como fallback (la
    genera al vuelo y queda cacheada para la próxima).
    """
    existing = _existing_clean_keys(event)
    storage = default_storage()
    for photo in photos:
        key = clean_key(event.slug, photo.id, "thumb")
        url = ""
        if key in existing:
            try:
                url = storage.get_signed_url(key, expires_in=_SIGNED_URL_TTL)
            except (R2NotConfiguredError, R2UploadError):
                url = ""
        if not url:
            url = reverse("reviewer:clean_image", kwargs={"photo_id": photo.id, "size": "thumb"})
        photo.clean_thumb_url = url  # type: ignore[attr-defined]


def warm_event_clean_renders(
    event: Event,
    *,
    sizes: Iterable[str] = ("thumb", "preview"),
    force: bool = False,
) -> dict[str, int]:
    """Pre-genera los renders limpios de TODAS las fotos aprobadas del evento.

    Idempotente: saltea las que ya existen (salvo `force`). Baja el original una
    sola vez por foto y genera todos los tamaños pedidos. Nunca propaga una
    excepción de una foto — la cuenta como error y sigue. Devuelve contadores.
    """
    storage = default_storage()
    existing: set[str] = set()
    if not force:
        try:
            existing = set(storage.list_keys(f"{CLEAN_PREFIX}/{event.slug}/"))
        except (R2NotConfiguredError, R2UploadError):
            existing = set()

    stats = {"generated": 0, "skipped": 0, "errors": 0}
    qs = (
        Photo.objects.filter(event=event, status=PhotoStatus.APPROVED)
        .exclude(original_key="")
        .only("id", "original_key")
    )
    for photo in qs.iterator(chunk_size=100):
        original: bytes | None = None
        for size in sizes:
            long_edge, quality = REVIEWER_CLEAN_SIZES[size]
            key = clean_key(event.slug, photo.id, size)
            if key in existing:
                stats["skipped"] += 1
                continue
            try:
                if original is None:
                    buf = BytesIO()
                    storage.download_fileobj(photo.original_key, buf)
                    original = buf.getvalue()
                data = generate_clean_render(original, long_edge, quality)
                storage.upload(
                    BytesIO(data),
                    key,
                    content_type="image/webp",
                    cache_control="private, max-age=604800",
                )
                stats["generated"] += 1
            except Exception:
                logger.exception("warm clean render falló para foto %s (%s)", photo.id, size)
                stats["errors"] += 1
    invalidate_existing_keys(event.slug)
    return stats

"""Avatares de caras para el "visor" del lightbox.

Cada `FaceEmbedding` ya tiene su bbox (píxeles absolutos sobre la foto
orientada). Acá recortamos esa caja a un cuadrado y lo subimos a R2 para
mostrarlo como avatar clickeable.

Decisión de producto (Jair, 2026-07): sólo se convierten en avatar las caras
**grandes y nítidas** — las del fondo (espectadores que no posaron, gente
movida) quedan fuera. El filtro es doble:

1. Tamaño: el lado de la cara tiene que llegar a `FACE_AVATAR_MIN_PX` en la
   foto original. Barato, se resuelve sin bajar la imagen.
2. Nitidez: varianza del Laplaciano sobre el recorte, en `imaging.py`. Requiere
   los píxeles, así que corre recién al generar.

NO se filtran menores: decisión explícita del dueño, coherente con tener el
blur apagado en prod (ver CLAUDE.md).
"""

from __future__ import annotations

import logging
from io import BytesIO

from django.conf import settings
from django.db.models import QuerySet

from apps.photos.imaging import FaceTooBlurryError, generate_face_avatar
from apps.photos.models import FaceEmbedding, Photo, PhotoStatus
from apps.photos.storage import (
    R2NotConfiguredError,
    R2Storage,
    R2UploadError,
    default_storage,
    key_for_face_avatar,
)

logger = logging.getLogger(__name__)


def _min_px() -> int:
    """Lado mínimo (px sobre el original) para que una cara sea avatar."""
    return int(getattr(settings, "FACE_AVATAR_MIN_PX", 90))


def face_size_px(bbox: dict[str, float] | None) -> float:
    """Lado mayor del bbox de la cara, en píxeles del original."""
    if not bbox:
        return 0.0
    try:
        w = float(bbox.get("x2", 0)) - float(bbox.get("x1", 0))
        h = float(bbox.get("y2", 0)) - float(bbox.get("y1", 0))
    except (TypeError, ValueError):
        return 0.0
    return max(w, h)


def is_avatar_sized(bbox: dict[str, float] | None, *, min_px: int | None = None) -> bool:
    """Filtro de tamaño (paso 1). El de nitidez corre al recortar."""
    return face_size_px(bbox) >= (min_px if min_px is not None else _min_px())


def avatar_faces_for_photo(photo: Photo) -> list[FaceEmbedding]:
    """Caras de la foto que YA tienen avatar generado, de mayor a menor.

    El orden por tamaño hace que el visor muestre primero a los protagonistas.
    """
    faces = list(photo.face_embeddings.exclude(avatar_key="").only("id", "bbox", "avatar_key"))
    faces.sort(key=lambda f: face_size_px(f.bbox), reverse=True)
    return faces


def pending_faces_for_event(event_id: int) -> QuerySet[FaceEmbedding]:
    """Caras sin avatar de fotos aprobadas del evento (candidatas al batch)."""
    return (
        FaceEmbedding.objects.filter(
            photo__event_id=event_id,
            photo__status=PhotoStatus.APPROVED,
            avatar_key="",
        )
        .exclude(photo__original_key="")
        .select_related("photo")
        .order_by("photo_id", "id")
    )


def generate_avatars_for_photo(
    photo: Photo,
    *,
    storage: R2Storage | None = None,
    image_bytes: bytes | None = None,
) -> dict[str, int]:
    """Genera los avatares de una foto. Idempotente (saltea los ya hechos).

    `image_bytes` permite reusar el original ya descargado por el caller.
    """
    store = storage or default_storage()
    faces = list(photo.face_embeddings.filter(avatar_key=""))
    candidates = [f for f in faces if is_avatar_sized(f.bbox)]
    stats = {"generated": 0, "too_small": len(faces) - len(candidates), "blurry": 0, "errors": 0}
    if not candidates:
        return stats

    if image_bytes is None:
        buf = BytesIO()
        try:
            store.download_fileobj(photo.original_key, buf)
        except (R2NotConfiguredError, R2UploadError):
            stats["errors"] += len(candidates)
            return stats
        image_bytes = buf.getvalue()

    for face in candidates:
        try:
            data = generate_face_avatar(image_bytes, face.bbox)
        except FaceTooBlurryError:
            stats["blurry"] += 1
            continue
        except Exception:  # imagen corrupta / bbox inconsistente
            logger.warning("avatar de cara falló", extra={"face_id": face.id})
            stats["errors"] += 1
            continue

        key = key_for_face_avatar(photo.event.slug, face.id)
        try:
            store.upload(BytesIO(data), key, content_type="image/webp")
        except (R2NotConfiguredError, R2UploadError):
            stats["errors"] += 1
            continue

        face.avatar_key = key
        face.save(update_fields=["avatar_key"])
        stats["generated"] += 1

    return stats

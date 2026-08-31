"""Avatares de caras para el "visor" del lightbox.

Cada `FaceEmbedding` ya tiene su bbox (píxeles absolutos sobre la foto
orientada). Acá recortamos esa caja a un cuadrado y lo subimos a R2 para
mostrarlo como avatar clickeable.

Decisión de producto (Jair, 2026-07): se privilegian las caras **grandes y
nítidas** — las del fondo (espectadores que no posaron, gente movida) quedan
atrás. El filtro es doble:

1. Tamaño: el lado de la cara tiene que llegar a `FACE_AVATAR_MIN_PX` en la
   foto original. Barato, se resuelve sin bajar la imagen.
2. Nitidez: varianza del Laplaciano sobre el recorte, en `imaging.py`. Requiere
   los píxeles, así que corre recién al generar.

...pero ese filtro solo NO alcanza en las FOTOS GRUPALES (Garmin Runners
Girls, 2026-08): en una foto de 25 personas cada cara mide ~50-60px, ninguna
llegaba a los 130px y la foto terminaba ofreciendo UNA sola cara (la del
respaldo de más abajo). Para las otras 24 corredoras, la búsqueda por cara
simplemente no existía en esa foto. Por eso hay un segundo escalón
(`FACE_AVATAR_FLOOR_PX`): las caras chicas también entran, sin exigirles
nitidez — una cara de 55px es blanda por definición y rechazarla por eso
anula el propósito. Ver `generate_avatars_for_photo`.

NO se filtran menores: decisión explícita del dueño, coherente con tener el
blur apagado en prod (ver CLAUDE.md).
"""

from __future__ import annotations

import logging
from io import BytesIO

from django.conf import settings
from django.db.models import QuerySet

from apps.photos.imaging import FACE_SHARPNESS_MIN, FaceTooBlurryError, generate_face_avatar
from apps.photos.models import FaceEmbedding, Photo, PhotoStatus
from apps.photos.storage import (
    R2NotConfiguredError,
    R2Storage,
    R2UploadError,
    default_storage,
    key_for_face_avatar,
)

logger = logging.getLogger(__name__)


# Lado mínimo (px sobre el original) para que una cara entre al visor.
# CALIBRADO con las 38,783 caras reales de Surf City (2026-07):
#   mín 20 · p25 132 · mediana 213 · p75 330 · p90 464 · máx 2251
# Las caras de foto profesional de carrera son grandes; un umbral de 90px
# dejaba pasar el 88% (no filtraba nada). 130px ≈ p25: corta el cuartil más
# chico, que es donde viven los espectadores del fondo, y deja visor en el
# 94% de las fotos. Con el margen del recorte (45%) tampoco hay que agrandar
# la imagen, así que el avatar sale nítido.
FACE_AVATAR_MIN_PX_DEFAULT = 130

# Piso absoluto: por debajo de esto la cara ya no se distingue ni para hacerle
# click. MEDIDO con las 1,159 caras del social run de Garmin (2026-08), donde
# conviven dos tipos de foto:
#   mín 28 · p25 50 · mediana 59 · p75 179 · p90 299 · máx 651
# La mediana de 59px es la foto grupal; el p75 de 179px, el primer plano. Con
# el corte en 130px quedaban afuera 802 de 1,159 caras (69%) y 38 fotos
# grupales ofrecían una sola persona. Bajando el piso a 50px entran 890 caras
# y 106 fotos pasan a ofrecer 3 o más personas.
FACE_AVATAR_FLOOR_PX_DEFAULT = 50


def _min_px() -> int:
    """Lado mínimo (px sobre el original) para que una cara sea avatar."""
    return int(getattr(settings, "FACE_AVATAR_MIN_PX", FACE_AVATAR_MIN_PX_DEFAULT))


def _floor_px() -> int:
    """Piso absoluto: caras más chicas que esto no se ofrecen."""
    return int(getattr(settings, "FACE_AVATAR_FLOOR_PX", FACE_AVATAR_FLOOR_PX_DEFAULT))


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
    piso = _floor_px()
    # Dos escalones, y cada candidata viaja con el umbral de nitidez que le
    # toca: el de siempre para las grandes, y ninguno para las chicas de foto
    # grupal — a 50-60px el Laplaciano las marca "movidas" a todas, y son
    # justamente las que hay que ofrecer.
    candidatas: list[tuple[FaceEmbedding, float]] = []
    for f in faces:
        if is_avatar_sized(f.bbox):
            candidatas.append((f, FACE_SHARPNESS_MIN))
        elif face_size_px(f.bbox) >= piso:
            candidatas.append((f, 0.0))
    candidates = [f for f, _ in candidatas]
    stats = {
        "generated": 0,
        "too_small": len(faces) - len(candidates),
        "blurry": 0,
        "errors": 0,
        "fallback": 0,
    }
    if not faces:
        return stats

    if image_bytes is None:
        buf = BytesIO()
        try:
            store.download_fileobj(photo.original_key, buf)
        except (R2NotConfiguredError, R2UploadError):
            stats["errors"] += len(candidates)
            return stats
        image_bytes = buf.getvalue()

    def _persist(face: FaceEmbedding, data: bytes) -> bool:
        key = key_for_face_avatar(photo.event.slug, face.id)
        try:
            store.upload(BytesIO(data), key, content_type="image/webp")
        except (R2NotConfiguredError, R2UploadError):
            stats["errors"] += 1
            return False
        face.avatar_key = key
        face.save(update_fields=["avatar_key"])
        return True

    for face, sharp in candidatas:
        try:
            data = generate_face_avatar(image_bytes, face.bbox, min_sharpness=sharp)
        except FaceTooBlurryError:
            stats["blurry"] += 1
            continue
        except Exception:  # imagen corrupta / bbox inconsistente
            logger.warning("avatar de cara falló", extra={"face_id": face.id})
            stats["errors"] += 1
            continue
        if _persist(face, data):
            stats["generated"] += 1

    # Garantía de cobertura: si NINGUNA cara pasó los filtros, igual mostramos
    # la más grande de la foto. Sin esto, una foto donde todas las caras son
    # chicas o están algo movidas quedaba sin visor — y para el corredor eso
    # se ve como que la función "no anda" en esa foto. El filtro sigue
    # decidiendo qué caras EXTRA se muestran; acá sólo aseguramos que no haya
    # fotos con gente y sin ninguna cara ofrecida.
    if stats["generated"] == 0:
        biggest = max(faces, key=lambda f: face_size_px(f.bbox))
        if face_size_px(biggest.bbox) > 0:
            try:
                data = generate_face_avatar(image_bytes, biggest.bbox, min_sharpness=0.0)
            except Exception:
                logger.warning("avatar de respaldo falló", extra={"photo_id": photo.id})
            else:
                if _persist(biggest, data):
                    stats["generated"] += 1
                    stats["fallback"] += 1

    return stats

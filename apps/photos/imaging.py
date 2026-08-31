"""Imaging pipeline: extract EXIF, generate preview (con watermark), thumbnail.

Todo en memoria → R2 directo. Nunca persistimos en filesystem del worker.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from PIL import ExifTags, Image, ImageDraw, ImageFont, ImageOps

from apps.photos.storage import (
    R2Storage,
    default_storage,
    key_for_branded,
    key_for_event_cover,
    key_for_photographer_cover,
    key_for_preview,
    key_for_thumbnail,
)

if TYPE_CHECKING:
    from apps.photos.models import Photo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
PREVIEW_LONG_EDGE = 1200
PREVIEW_QUALITY = 80
# Thumb del grid: 640px (era 400). En desktop/retina cada celda del contact
# sheet se ve a ~600-800px reales; con 400px el thumb se agrandaba y salía
# borroso. WebP q78 mantiene el archivo chico (~40-60KB) → sigue rápido con
# lazy-load + paginación de 60/página.
THUMB_LONG_EDGE = 640
THUMB_QUALITY = 78

WATERMARK_OPACITY = 38  # 0-255 (~15%)
WATERMARK_ANGLE = -30


# ---------------------------------------------------------------------------
# Orientación EXIF
# ---------------------------------------------------------------------------
def _open_oriented(source_path: Path) -> Image.Image:
    """Abre la imagen y la ROTA según la orientación EXIF.

    Las cámaras (y celulares) guardan las fotos VERTICALES como horizontales +
    una etiqueta EXIF que dice "rotá 90°". Si abrimos con `Image.open` sin más,
    trabajamos sobre los píxeles crudos (de costado) → la vertical sale acostada
    y, peor, los logos se pegan en el borde equivocado. `exif_transpose` aplica
    esa rotación y deja la imagen como se debe VER, sin la etiqueta."""
    img = Image.open(source_path)
    return ImageOps.exif_transpose(img) or img


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------
def extract_exif_and_dimensions(photo: Photo, source_path: Path) -> None:
    """Pobla los campos EXIF + width/height/file_size en `photo`.

    No hace `save()` — la task que lo llama decide cuándo persistir.
    """
    with Image.open(source_path) as img:
        exif = _exif_to_dict(img)
        # width/height de cómo se VE (ya rotada), no de los píxeles crudos.
        oriented = ImageOps.exif_transpose(img) or img
        photo.width = oriented.width
        photo.height = oriented.height

    photo.exif_raw = exif
    photo.capture_time = _parse_capture_time(exif)
    photo.camera_make = (exif.get("Make") or "").strip()[:100]
    photo.camera_model = (exif.get("Model") or "").strip()[:100]
    photo.lens_model = (exif.get("LensModel") or "").strip()[:200]
    photo.iso = _safe_int(exif.get("ISOSpeedRatings"))
    photo.focal_length = _format_focal(exif.get("FocalLength"))
    photo.aperture = _format_aperture(exif.get("FNumber"))
    photo.shutter_speed = _format_shutter(exif.get("ExposureTime"))


def _exif_to_dict(img: Image.Image) -> dict[str, Any]:
    raw = img.getexif()
    if not raw:
        return {}
    result: dict[str, Any] = {}
    # IFD principal: Make, Model, Orientation y `DateTime` (= hora en que se
    # GUARDÓ/exportó el archivo, NO el disparo).
    for tag_id, value in raw.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        result[tag] = _make_json_safe(value)
    # Sub-IFD de EXIF: acá viven `DateTimeOriginal` (hora del DISPARO),
    # OffsetTime, ISO, FNumber, ExposureTime, FocalLength, LensModel, etc.
    # Sin leerlo, la hora caía a `DateTime` (la de exportado → "hora rara") y los
    # datos de cámara salían vacíos en el drawer de aprobación.
    try:
        sub_ifd = raw.get_ifd(ExifTags.IFD.Exif)
    except (AttributeError, KeyError, OSError, ValueError):
        sub_ifd = {}
    for tag_id, value in sub_ifd.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        result.setdefault(tag, _make_json_safe(value))  # no pisar el IFD principal
    return result


def _strip_nulls(text: str) -> str:
    """Postgres jsonb NO acepta \\u0000 dentro de strings (DataError) — y las
    cámaras meten bytes nulos en tags EXIF binarios (p.ej. ComponentsConfiguration
    de Canon). Sin esta limpieza, el save() de process_photo explota y la foto
    queda clavada en "procesando" (incidente del evento Camino, 2026-06-09)."""
    return text.replace("\x00", "")


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return _strip_nulls(value.decode("utf-8", errors="ignore"))
        except Exception:
            return None
    if isinstance(value, str):
        return _strip_nulls(value)
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, int | float | bool) or value is None:
        return value
    return _strip_nulls(str(value))


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_capture_time(exif: dict[str, Any]) -> Any:
    """Hora del DISPARO. EXIF la guarda como `'2026:05:14 09:23:11'` en hora local
    de la cámara, SIN zona. La interpretamos como hora de El Salvador (el
    `TIME_ZONE` del proyecto) — el `OffsetTime` del EXIF se ignora a propósito
    porque las cámaras suelen traerlo mal configurado (ej. `-12:00`).

    Prioridad: DateTimeOriginal (disparo) > DateTimeDigitized > DateTime (guardado).
    """
    from datetime import datetime

    from django.utils import timezone

    raw = exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or exif.get("DateTime")
    if not raw:
        return None
    try:
        dt = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    if timezone.is_naive(dt):
        # make_aware con el TIME_ZONE configurado (El Salvador), no el "activo",
        # para que sea correcto también en el worker de Celery.
        return timezone.make_aware(dt, timezone.get_default_timezone())
    return dt


def _format_focal(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{round(float(value))}mm"
    except (TypeError, ValueError):
        return ""


def _format_aperture(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"f/{float(value):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def _format_shutter(value: Any) -> str:
    if value is None:
        return ""
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return ""
    if secs >= 1:
        return f"{secs:g}s"
    return f"1/{round(1 / secs)}s"


# ---------------------------------------------------------------------------
# Branding: logos de marca por evento (reemplaza el watermark) o watermark normal
# ---------------------------------------------------------------------------
def _try_brand_overlay(img: Image.Image, photo: Photo) -> Image.Image | None:
    """Si el evento tiene `brand_overlay` con un template válido, devuelve la
    imagen RGB con los logos pegados. Devuelve None si no aplica o si falla, para
    que el llamador caiga al comportamiento normal (watermark). NUNCA propaga
    excepciones → un logo faltante no puede romper el procesamiento de la foto."""
    template = getattr(photo.event, "brand_overlay", "") or ""
    if not template:
        return None
    try:
        from apps.photos.overlays import apply_brand_overlay, is_valid_template

        if is_valid_template(template):
            return apply_brand_overlay(img, template)
    except Exception:
        logger.exception(
            "brand overlay falló (event=%s) — fallback a watermark",
            getattr(photo.event, "slug", "?"),
        )
    return None


# ---------------------------------------------------------------------------
# Preview con watermark (o logos de marca)
# ---------------------------------------------------------------------------
def generate_preview(
    photo: Photo,
    source_path: Path | None = None,
    *,
    img_object: Image.Image | None = None,
    storage: R2Storage | None = None,
) -> str:
    """Genera preview y lo sube a R2. Devuelve el key.

    Si el evento tiene `brand_overlay`, se pegan los logos de marca en las
    esquinas (ej. Surf City). Si no, lleva watermark diagonal — salvo que
    `PREVIEW_WATERMARK_ENABLED` esté en false (así corre prod), y entonces el
    preview sale limpio.
    Acepta `source_path` (lee de disco) o `img_object` (imagen ya cargada,
    p.ej. con blur de menores aplicado).
    """
    img = img_object.copy() if img_object is not None else _open_oriented(source_path)  # type: ignore[arg-type]
    img.thumbnail((PREVIEW_LONG_EDGE, PREVIEW_LONG_EDGE), Image.Resampling.LANCZOS)

    final = _try_brand_overlay(img, photo)
    if final is None:
        if getattr(settings, "PREVIEW_WATERMARK_ENABLED", True):
            watermark_text = f"{settings.SITE_NAME.upper()} · {photo.event.name.upper()}"
            final = apply_diagonal_watermark(img, watermark_text)
        else:
            final = img

    buf = BytesIO()
    final.save(buf, format="WEBP", quality=PREVIEW_QUALITY, method=6)
    buf.seek(0)

    key = key_for_preview(photo.event.slug, _photo_uid(photo))
    (storage or default_storage()).upload(buf, key, content_type="image/webp")
    return key


def generate_thumbnail(
    photo: Photo,
    source_path: Path | None = None,
    *,
    img_object: Image.Image | None = None,
    storage: R2Storage | None = None,
) -> str:
    """Thumb sin watermark (es pequeño). Si el evento tiene `brand_overlay`, sí
    lleva los logos de marca (para que la galería se vea brandeada)."""
    img = img_object.copy() if img_object is not None else _open_oriented(source_path)  # type: ignore[arg-type]
    img.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.Resampling.LANCZOS)

    rgb = img.convert("RGB")
    branded = _try_brand_overlay(rgb, photo)
    if branded is not None:
        rgb = branded

    buf = BytesIO()
    rgb.save(buf, format="WEBP", quality=THUMB_QUALITY, method=6)
    buf.seek(0)

    key = key_for_thumbnail(photo.event.slug, _photo_uid(photo))
    (storage or default_storage()).upload(buf, key, content_type="image/webp")
    return key


# ---------------------------------------------------------------------------
# Render LIMPIO (sin logos ni watermark) — para el área de invitados
# ---------------------------------------------------------------------------
# (size_key -> (lado_largo_px, calidad_webp))
REVIEWER_CLEAN_SIZES: dict[str, tuple[int, int]] = {
    "thumb": (640, 80),
    "preview": (1600, 82),
}


def generate_clean_render(original_bytes: bytes, long_edge: int, quality: int) -> bytes:
    """Versión SIN logos ni watermark del original, a `long_edge` px, WebP.

    Toma los bytes del original (JPEG en alta) y devuelve los bytes de un WebP
    reducido y limpio (honra la orientación EXIF). NO aplica logos de marca — es
    para el área de invitados, donde se ve y se baja todo sin marca.
    """
    img: Image.Image = Image.open(BytesIO(original_bytes))
    img = ImageOps.exif_transpose(img) or img
    img.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.convert("RGB").save(buf, format="WEBP", quality=quality, method=6)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Original con logos de marca (lo que se DESCARGA en eventos brandeados)
# ---------------------------------------------------------------------------
BRANDED_QUALITY = 92


def generate_branded_original(
    photo: Photo,
    source_path: Path | None = None,
    *,
    img_object: Image.Image | None = None,
    storage: R2Storage | None = None,
) -> str | None:
    """Genera el ORIGINAL full-res CON los logos de marca y lo sube a R2.

    Sólo aplica si el evento tiene `brand_overlay` con un template válido; en ese
    caso devuelve el key de la versión brandeada (lo que se DESCARGA en ese
    evento). Devuelve None si el evento no tiene overlay o si algo falla — NUNCA
    propaga excepción, así un problema con los logos no rompe el procesamiento de
    la foto (la descarga simplemente cae al original limpio).

    Es consistente con el preview: usa el MISMO motor de overlay y la misma
    orientación (no re-orienta por EXIF), sólo que a resolución completa y en
    JPEG. El JPEG se guarda SIN EXIF (sin tag de orientación) → el visor lo muestra
    tal cual, con los logos en las esquinas de abajo, en horizontal y vertical.
    """
    template = getattr(photo.event, "brand_overlay", "") or ""
    if not template:
        return None
    try:
        from apps.photos.overlays import apply_brand_overlay, is_valid_template

        if not is_valid_template(template):
            return None
        img = img_object.copy() if img_object is not None else _open_oriented(source_path)  # type: ignore[arg-type]
        branded = apply_brand_overlay(img, template)  # full-res, mismos % que el preview

        buf = BytesIO()
        branded.save(buf, format="JPEG", quality=BRANDED_QUALITY, optimize=True)
        buf.seek(0)

        key = key_for_branded(photo.event.slug, _photo_uid(photo))
        (storage or default_storage()).upload(buf, key, content_type="image/jpeg")
        return key
    except Exception:
        logger.exception(
            "generate_branded_original falló (event=%s) — la descarga usará el original limpio",
            getattr(photo.event, "slug", "?"),
        )
        return None


# ---------------------------------------------------------------------------
# Portadas (evento + carpeta de fotógrafo)
# ---------------------------------------------------------------------------
COVER_LONG_EDGE = 1400
COVER_QUALITY = 82


def _process_cover_to_key(file_obj: Any, key: str, storage: R2Storage | None = None) -> str:
    """Procesa una imagen de portada (resize → WebP, SIN watermark, honra EXIF)
    y la sube a R2 bajo `key`. `file_obj`: UploadedFile / file-like / bytes."""
    src: Any = BytesIO(file_obj) if isinstance(file_obj, (bytes, bytearray)) else file_obj
    img: Image.Image = Image.open(src)
    img = ImageOps.exif_transpose(img) or img  # rota según EXIF (fotos de celular)
    img.thumbnail((COVER_LONG_EDGE, COVER_LONG_EDGE), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.convert("RGB").save(buf, format="WEBP", quality=COVER_QUALITY, method=6)
    buf.seek(0)

    (storage or default_storage()).upload(buf, key, content_type="image/webp")
    return key


def process_event_cover(file_obj: Any, event_slug: str, *, storage: R2Storage | None = None) -> str:
    """Portada del evento → WebP → R2. Devuelve el key."""
    return _process_cover_to_key(file_obj, key_for_event_cover(event_slug), storage)


def process_photographer_cover(
    file_obj: Any, link_id: int, *, storage: R2Storage | None = None
) -> str:
    """Imagen destacada de la carpeta del fotógrafo → WebP → R2. Devuelve el key."""
    return _process_cover_to_key(file_obj, key_for_photographer_cover(link_id), storage)


# ---------------------------------------------------------------------------
# Blur de menores (Fase 4)
# ---------------------------------------------------------------------------
MINOR_BLUR_RADIUS = 30
MINOR_BBOX_MARGIN = 0.2  # expandir el bbox 20% para cubrir toda la cara


def blur_minor_faces_and_regenerate(
    photo: Photo,
    source_path: Path,
    minor_faces: list[Any],
    *,
    storage: R2Storage | None = None,
) -> tuple[str, str, str | None]:
    """Aplica blur gaussiano a las caras de menores y regenera preview+thumb (y,
    en eventos brandeados, el original con logos).

    El ORIGINAL no se toca: trabajamos sobre una copia en memoria. Devuelve
    `(preview_key, thumbnail_key, branded_key)` — `branded_key` es None si el
    evento no tiene `brand_overlay`. Importante: el original con logos también se
    regenera desde la copia BLUREADA, así la descarga nunca muestra un menor sin
    blur si el blur está activado.
    """
    from PIL import ImageFilter

    img = _open_oriented(source_path).convert("RGB")
    w, h = img.size

    for face in minor_faces:
        bbox = face.bbox or {}
        try:
            x1 = float(bbox["x1"])
            y1 = float(bbox["y1"])
            x2 = float(bbox["x2"])
            y2 = float(bbox["y2"])
        except (KeyError, TypeError, ValueError):
            continue

        bw, bh = x2 - x1, y2 - y1
        x1 = max(0, int(x1 - bw * MINOR_BBOX_MARGIN))
        y1 = max(0, int(y1 - bh * MINOR_BBOX_MARGIN))
        x2 = min(w, int(x2 + bw * MINOR_BBOX_MARGIN))
        y2 = min(h, int(y2 + bh * MINOR_BBOX_MARGIN))
        if x2 <= x1 or y2 <= y1:
            continue

        region = img.crop((x1, y1, x2, y2))
        blurred = region.filter(ImageFilter.GaussianBlur(radius=MINOR_BLUR_RADIUS))
        img.paste(blurred, (x1, y1))

    preview_key = generate_preview(photo, img_object=img, storage=storage)
    thumb_key = generate_thumbnail(photo, img_object=img, storage=storage)
    branded_key = generate_branded_original(photo, img_object=img, storage=storage)
    return preview_key, thumb_key, branded_key


def _photo_uid(photo: Photo) -> str:
    """UUID estable derivado del `original_key` (el filename ya es uuid)."""
    from apps.photos.storage import photo_uuid_from_key

    if photo.original_key:
        return photo_uuid_from_key(photo.original_key)
    # Fallback (no debería pasar en producción).
    return str(photo.pk)


# ---------------------------------------------------------------------------
# Watermark diagonal
# ---------------------------------------------------------------------------
_DEFAULT_FONT_PATH = (
    Path(settings.BASE_DIR) / "static" / "fonts" / "space-grotesk-latin-700-normal.woff2"
)


def apply_diagonal_watermark(img: Image.Image, text: str) -> Image.Image:
    """Marca de agua diagonal repetida — replica el lightbox del design system."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    font_size = max(14, img.width // 80)
    font = _load_watermark_font(font_size=font_size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    spacing_x = font_size * 25
    spacing_y = font_size * 8

    text_with_sep = f"  {text}  •  "
    for y in range(-img.height, img.height * 2, spacing_y):
        for x in range(-img.width, img.width * 2, spacing_x):
            draw.text((x, y), text_with_sep, fill=(255, 255, 255, WATERMARK_OPACITY), font=font)

    layer = layer.rotate(WATERMARK_ANGLE, resample=Image.Resampling.BICUBIC, expand=False)
    combined = Image.alpha_composite(img, layer)
    return combined.convert("RGB")


def _load_watermark_font(font_size: int) -> Any:
    """Carga Space Grotesk si está, sino fallback al default de PIL.

    Pillow no lee .woff2 directamente; preferimos .ttf si está. Si no, default.
    Devolvemos `Any` porque `ImageFont.truetype` y `ImageFont.load_default`
    devuelven clases distintas (`FreeTypeFont` vs `ImageFont`).
    """
    candidates = [
        Path(settings.BASE_DIR) / "static" / "fonts" / "SpaceGrotesk-Bold.ttf",
        Path(settings.BASE_DIR) / "static" / "fonts" / "Inter-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), font_size)
            except OSError:
                continue
    # Default PIL font (no incluye los pesos del design system pero funciona).
    return ImageFont.load_default(size=font_size)


# ---------------------------------------------------------------------------
# Avatares de caras (visor del lightbox)
# ---------------------------------------------------------------------------
# Lado del recorte cuadrado. En la UI el tile se ve a ~52px; 160 cubre retina
# (2x) y deja margen para el drawer del dashboard, que lo muestra más grande.
FACE_AVATAR_SIZE = 160
FACE_AVATAR_QUALITY = 82
# Cuánto se agranda el bbox de la cara para el recorte. InsightFace devuelve
# la caja justa de la cara; sin aire, el avatar queda cortado en la frente y
# el mentón y se lee mal a 52px.
FACE_AVATAR_MARGIN = 0.45
# Umbral de nitidez (varianza del Laplaciano sobre el recorte en gris). Las
# caras del fondo salen movidas/desenfocadas; con esto no se vuelven avatar.
# MEDIDO en prod: con 42.0 se descartaban 6.925 de 29.294 caras (24%) y 3.201
# fotos quedaban SIN visor — demasiado exigente. Bajado a 15.0, que sigue
# cortando los recortes realmente ilegibles. Además, `faces.py` garantiza al
# menos una cara por foto (la más grande) aunque no llegue al umbral, así que
# este número ya no decide la cobertura, sólo cuántas caras EXTRA se muestran.
FACE_SHARPNESS_MIN = 15.0


class FaceTooBlurryError(Exception):
    """El recorte no pasa el umbral de nitidez → no se genera avatar."""


def _square_face_box(
    bbox: dict[str, float], img_w: int, img_h: int, *, margin: float = FACE_AVATAR_MARGIN
) -> tuple[int, int, int, int]:
    """Convierte el bbox de la cara en una caja CUADRADA con aire, clampeada a
    los bordes de la imagen. `bbox` viene en píxeles absolutos {x1,y1,x2,y2}."""
    x1, y1 = float(bbox.get("x1", 0)), float(bbox.get("y1", 0))
    x2, y2 = float(bbox.get("x2", 0)), float(bbox.get("y2", 0))
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * (1 + margin)
    # Clampear el lado antes de centrar evita pedir un recorte más grande que
    # la imagen (pasa con caras muy cerca del borde en fotos verticales).
    side = min(side, float(min(img_w, img_h)))
    half = side / 2
    left = round(min(max(cx - half, 0), img_w - side))
    top = round(min(max(cy - half, 0), img_h - side))
    return left, top, left + round(side), top + round(side)


def _sharpness(img: Image.Image) -> float:
    """Varianza del Laplaciano en escala de grises: proxy estándar de nitidez."""
    import numpy as np

    gray = np.asarray(img.convert("L"), dtype=np.float64)
    if gray.size == 0:
        return 0.0
    # Kernel Laplaciano 3x3 aplicado con slicing (sin scipy).
    lap = (
        -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    )
    return float(lap.var()) if lap.size else 0.0


def generate_face_avatar(
    image_bytes: bytes,
    bbox: dict[str, float],
    *,
    size: int = FACE_AVATAR_SIZE,
    min_sharpness: float = FACE_SHARPNESS_MIN,
) -> bytes:
    """Recorta la cara de `image_bytes` y devuelve un WebP cuadrado.

    Lanza `FaceTooBlurryError` si el recorte no llega al umbral de nitidez
    (caras del fondo, movidas o fuera de foco). El caller decide qué hacer.
    """
    img: Image.Image = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img) or img
    img = img.convert("RGB")

    box = _square_face_box(bbox, img.width, img.height)
    face = img.crop(box)

    if _sharpness(face) < min_sharpness:
        raise FaceTooBlurryError(f"nitidez < {min_sharpness}")

    face = face.resize((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    face.save(buf, format="WEBP", quality=FACE_AVATAR_QUALITY, method=6)
    buf.seek(0)
    return buf.getvalue()

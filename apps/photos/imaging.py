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
THUMB_LONG_EDGE = 400
THUMB_QUALITY = 75

WATERMARK_OPACITY = 38  # 0-255 (~15%)
WATERMARK_ANGLE = -30


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------
def extract_exif_and_dimensions(photo: Photo, source_path: Path) -> None:
    """Pobla los campos EXIF + width/height/file_size en `photo`.

    No hace `save()` — la task que lo llama decide cuándo persistir.
    """
    with Image.open(source_path) as img:
        photo.width = img.width
        photo.height = img.height
        exif = _exif_to_dict(img)

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
# Preview con watermark
# ---------------------------------------------------------------------------
def generate_preview(
    photo: Photo,
    source_path: Path | None = None,
    *,
    img_object: Image.Image | None = None,
    storage: R2Storage | None = None,
) -> str:
    """Genera preview con watermark diagonal y lo sube a R2. Devuelve el key.

    Acepta `source_path` (lee de disco) o `img_object` (imagen ya cargada,
    p.ej. con blur de menores aplicado).
    """
    img = img_object.copy() if img_object is not None else Image.open(source_path)  # type: ignore[arg-type]
    img.thumbnail((PREVIEW_LONG_EDGE, PREVIEW_LONG_EDGE), Image.Resampling.LANCZOS)
    watermark_text = f"{settings.SITE_NAME.upper()} · {photo.event.name.upper()}"
    watermarked = apply_diagonal_watermark(img, watermark_text)

    buf = BytesIO()
    watermarked.save(buf, format="WEBP", quality=PREVIEW_QUALITY, method=6)
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
    """Thumb sin watermark (es pequeño, no vale la pena)."""
    img = img_object.copy() if img_object is not None else Image.open(source_path)  # type: ignore[arg-type]
    img.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.convert("RGB").save(buf, format="WEBP", quality=THUMB_QUALITY, method=6)
    buf.seek(0)

    key = key_for_thumbnail(photo.event.slug, _photo_uid(photo))
    (storage or default_storage()).upload(buf, key, content_type="image/webp")
    return key


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
) -> tuple[str, str]:
    """Aplica blur gaussiano a las caras de menores y regenera preview+thumb.

    El ORIGINAL no se toca: trabajamos sobre una copia en memoria. Devuelve
    `(preview_key, thumbnail_key)`.
    """
    from PIL import ImageFilter

    img = Image.open(source_path).convert("RGB")
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
    return preview_key, thumb_key


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

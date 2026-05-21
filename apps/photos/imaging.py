"""Imaging pipeline: extract EXIF, generate preview (con watermark), thumbnail.

Todo en memoria → R2 directo. Nunca persistimos en filesystem del worker.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from PIL import ExifTags, Image, ImageDraw, ImageFont

from apps.photos.storage import (
    R2Storage,
    default_storage,
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
    for tag_id, value in raw.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        result[tag] = _make_json_safe(value)
    return result


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(value, dict | list | tuple):
        return [_make_json_safe(v) for v in value] if isinstance(value, list | tuple) else value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_capture_time(exif: dict[str, Any]) -> Any:
    """EXIF guarda fechas tipo `'2026:05:14 09:23:11'`."""
    raw = exif.get("DateTimeOriginal") or exif.get("DateTime")
    if not raw:
        return None
    try:
        from datetime import datetime

        dt = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        from django.utils import timezone

        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
    except (ValueError, TypeError):
        return None


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
    source_path: Path,
    *,
    storage: R2Storage | None = None,
) -> str:
    """Genera preview con watermark diagonal y lo sube a R2. Devuelve el key."""
    img = Image.open(source_path)
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
    source_path: Path,
    *,
    storage: R2Storage | None = None,
) -> str:
    """Thumb sin watermark (es pequeño, no vale la pena)."""
    img = Image.open(source_path)
    img.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.convert("RGB").save(buf, format="WEBP", quality=THUMB_QUALITY, method=6)
    buf.seek(0)

    key = key_for_thumbnail(photo.event.slug, _photo_uid(photo))
    (storage or default_storage()).upload(buf, key, content_type="image/webp")
    return key


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

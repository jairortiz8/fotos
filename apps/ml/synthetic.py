"""Generador de fotos sintéticas con números de dorsal grandes.

Útil para tests (OCR sin dependencias externas) y para validación end-to-end
del pipeline sin necesidad de fotos reales.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def make_synthetic_bib_photo(
    bib_number: str,
    *,
    width: int = 1600,
    height: int = 2400,
    bg: tuple[int, int, int] = (40, 40, 45),
    bib_color: tuple[int, int, int] = (252, 82, 0),  # naranja brand
    text_color: tuple[int, int, int] = (250, 250, 250),
) -> Image.Image:
    """Imagen JPG simulando un corredor con un dorsal del número dado."""
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Cuerpo: rectángulo con bordes redondeados (simula torso)
    body_w = int(width * 0.6)
    body_h = int(height * 0.7)
    body_x = (width - body_w) // 2
    body_y = int(height * 0.18)
    _rounded_rect(draw, (body_x, body_y, body_x + body_w, body_y + body_h), 40, (60, 60, 70))

    # Dorsal: rectángulo más chico, encima
    bib_w = int(body_w * 0.7)
    bib_h = int(body_h * 0.4)
    bib_x = (width - bib_w) // 2
    bib_y = body_y + int(body_h * 0.2)
    _rounded_rect(draw, (bib_x, bib_y, bib_x + bib_w, bib_y + bib_h), 20, bib_color)

    # Número grande, centrado en el dorsal
    font = _load_big_font(min(bib_w // (max(1, len(bib_number)) + 1), bib_h - 80))
    bbox = draw.textbbox((0, 0), bib_number, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = bib_x + (bib_w - text_w) // 2
    ty = bib_y + (bib_h - text_h) // 2 - bbox[1]
    draw.text((tx, ty), bib_number, fill=text_color, font=font)

    return img


def write_synthetic_jpeg(
    bib_number: str,
    target: Path | str | None = None,
    **kwargs: Any,
) -> Path:
    """Genera y guarda un JPG sintético. Devuelve el path."""
    img = make_synthetic_bib_photo(bib_number, **kwargs)
    if target is None:
        import tempfile

        # `delete=False` para que sobreviva fuera del context; lo limpia el caller.
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
            path = Path(fh.name)
    else:
        path = Path(target)
    img.save(path, format="JPEG", quality=92)
    return path


def synthetic_jpeg_bytes(bib_number: str, **kwargs: Any) -> bytes:
    """Devuelve los bytes JPG en memoria (útil para tests de upload con HTTP)."""
    img = make_synthetic_bib_photo(bib_number, **kwargs)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    coords: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int],
) -> None:
    draw.rounded_rectangle(coords, radius=radius, fill=fill)


def _load_big_font(size: int) -> Any:
    """Trata de cargar Space Grotesk; si no, usa el default de PIL."""
    from django.conf import settings

    candidates = [
        Path(settings.BASE_DIR) / "static" / "fonts" / "SpaceGrotesk-Bold.ttf",
        Path(settings.BASE_DIR) / "static" / "fonts" / "Inter-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)

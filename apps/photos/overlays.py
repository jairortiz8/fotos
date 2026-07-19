"""Overlay de logos de marca por evento (ej. Surf City).

Pega 2 logos PNG transparentes en las esquinas de abajo de la foto, escalados a
un % del ANCHO (no en px fijos) → queda proporcionado igual en horizontal y
vertical, a cualquier resolución. Los logos blancos llevan una sombra suave
detrás para que se lean sobre fondos claros (cielo).

Se activa SOLO cuando `Event.brand_overlay` apunta a un template definido acá.
Cualquier fallo (asset faltante, imagen rara) NO debe romper el pipeline: el
llamador (imaging.generate_preview/thumbnail) captura la excepción y cae al
comportamiento normal (watermark).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageFilter

OVERLAY_DIR = Path(settings.BASE_DIR) / "apps" / "photos" / "brand_overlays"


@dataclass(frozen=True)
class OverlayTemplate:
    """Config de un template de logos. Los `*_w_pct`/`margin_pct` son fracción
    del ANCHO de la foto (no px) → proporcionado en horizontal y vertical.

    `landscape_scale`: en fotos HORIZONTALES (ancho ≥ alto) los logos se
    multiplican por este factor. Una horizontal es mucho más ancha, así que al
    escalar por el ancho los logos salían más grandes que en una vertical; con
    <1.0 se achican sólo en horizontal (las verticales quedan igual)."""

    left: str  # archivo del logo abajo-izquierda
    right: str  # archivo del logo abajo-derecha
    left_w_pct: float
    right_w_pct: float
    margin_pct: float
    landscape_scale: float = 1.0


TEMPLATES: dict[str, OverlayTemplate] = {
    "surf_city": OverlayTemplate(
        left="surf_city_left.png",  # Surf City Half Marathon
        right="elsalvador_right.png",  # elsalvador.travel + redes
        left_w_pct=0.22,
        right_w_pct=0.24,
        margin_pct=0.032,
        landscape_scale=0.8,  # en horizontal, logos 20% más chicos (verticales igual)
    ),
}


def is_valid_template(template: str) -> bool:
    return bool(template) and template in TEMPLATES


@lru_cache(maxsize=8)
def _load_logo(filename: str) -> Image.Image:
    """Carga (y cachea) un logo PNG en RGBA. lru_cache → se lee una sola vez por
    proceso del worker."""
    return Image.open(OVERLAY_DIR / filename).convert("RGBA")


def _soft_shadow(logo: Image.Image, blur: int, alpha: int = 150) -> Image.Image:
    """Sombra difusa oscura con la forma del logo (para legibilidad sobre claro)."""
    a = logo.split()[3]
    shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", logo.size, (0, 0, 0, alpha)), (0, 0), a)
    return shadow.filter(ImageFilter.GaussianBlur(blur))


def apply_brand_overlay(img: Image.Image, template: str) -> Image.Image:
    """Devuelve una copia RGB de `img` con los 2 logos pegados en las esquinas
    de abajo. Si el template no existe, devuelve la imagen tal cual (RGB)."""
    cfg = TEMPLATES.get(template)
    if cfg is None:
        return img.convert("RGB")

    base = img.convert("RGBA")
    w, h = base.size
    margin = round(w * cfg.margin_pct)
    blur = max(2, round(w * 0.004))
    # En horizontal (ancho ≥ alto) achicamos los logos por `landscape_scale`;
    # en vertical se quedan como están (factor 1.0).
    scale = cfg.landscape_scale if w >= h else 1.0

    def _scaled(logo: Image.Image, w_pct: float) -> Image.Image:
        target_w = max(1, round(w * w_pct * scale))
        target_h = max(1, round(target_w * logo.height / logo.width))
        return logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    left = _scaled(_load_logo(cfg.left), cfg.left_w_pct)
    right = _scaled(_load_logo(cfg.right), cfg.right_w_pct)

    placements = (
        (left, margin),  # abajo-izquierda
        (right, w - right.width - margin),  # abajo-derecha
    )
    for logo, x in placements:
        y = h - logo.height - margin
        base.alpha_composite(_soft_shadow(logo, blur), (x, y))
        base.alpha_composite(logo, (x, y))

    return base.convert("RGB")

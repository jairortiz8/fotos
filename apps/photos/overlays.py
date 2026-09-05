"""Overlay de logos de marca por evento (ej. Surf City, SÉPTIMO x CEP).

Hay dos formas de armar un template:

- `CornersTemplate`: 2 logos en las esquinas de abajo (Surf City).
- `StackedTemplate`: N filas de logos apiladas abajo, sobre un degradado negro
  (SÉPTIMO x CEP: 2 principales arriba de 3 patrocinadores).

En los dos casos los tamaños son PORCENTAJES, no px: quedan proporcionados a
cualquier resolución. Los de esquinas escalan por el ANCHO; los apilados por el
LADO CORTO de la foto, así una horizontal no se llena de logos gigantes.

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
class CornersTemplate:
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


@dataclass(frozen=True)
class LogoSpec:
    """Un logo dentro de una fila. `scale` ajusta su alto respecto al de la fila
    (los logos vienen con aire distinto alrededor; esto los empareja a ojo)."""

    filename: str
    scale: float = 1.0


@dataclass(frozen=True)
class LogoRow:
    """Una fila de logos. `h_pct` es el alto del logo como fracción del LADO
    CORTO de la foto → mismo tamaño aparente en vertical y en horizontal.

    `spread`: "justificado" reparte los logos de margen a margen con aire igual
    entre ellos; "centrado" los agrupa en el medio."""

    logos: tuple[LogoSpec, ...]
    h_pct: float
    spread: str = "justificado"


@dataclass(frozen=True)
class StackedTemplate:
    """N filas de logos apiladas abajo, sobre un degradado negro.

    Las filas van de arriba hacia abajo. Los porcentajes son fracción del LADO
    CORTO de la foto, salvo `margin_x_pct` y `center_gap_pct` que son del ANCHO
    (son distancias horizontales)."""

    rows: tuple[LogoRow, ...]
    margin_x_pct: float = 0.12  # margen lateral; 12% deja los logos fuera del recorte de IG
    bottom_pct: float = 0.063  # aire libre debajo de todo
    row_gap_pct: float = 0.045  # aire entre una fila y la siguiente
    center_gap_pct: float = 0.055  # aire entre logos de una fila "centrada"
    scrim_factor: float = 1.6  # alto del degradado respecto al bloque de logos
    scrim_alpha: int = 225  # opacidad máxima del degradado (0-255)
    # Ajustes SÓLO para fotos horizontales (ancho ≥ alto). Una horizontal es
    # mucho más ancha: con el mismo margen la fila queda desparramada de punta a
    # punta, y con el mismo alto los logos se ven chicos. Estos dos la vuelven a
    # dejar con la misma proporción que la vertical.
    landscape_margin_x_pct: float = 0.20
    landscape_scale: float = 1.15


TEMPLATES: dict[str, CornersTemplate | StackedTemplate] = {
    "surf_city": CornersTemplate(
        left="surf_city_left.png",  # Surf City Half Marathon
        right="elsalvador_right.png",  # elsalvador.travel + redes
        left_w_pct=0.22,
        right_w_pct=0.24,
        margin_pct=0.032,
        landscape_scale=0.8,  # en horizontal, logos 20% más chicos (verticales igual)
    ),
    # SÉPTIMO X CEP · SOCIAL RUN: los 5 logos abajo, en dos filas. Arriba los dos
    # principales (SÉPTIMO ROOFTOP + cep) juntos al centro; debajo los tres
    # patrocinadores repartidos de margen a margen.
    "septimo_cep": StackedTemplate(
        rows=(
            LogoRow(
                logos=(
                    LogoSpec("SR2026_whiteP.png"),
                    LogoSpec("cep blanco.png", scale=0.80),
                ),
                h_pct=0.084,
                spread="centrado",
            ),
            LogoRow(
                logos=(
                    LogoSpec("GU_Secondary_White_Transparent.png"),
                    LogoSpec("LOGO TASU-01.png", scale=1.05),
                    LogoSpec("NUGO LOGO WHITE.webp", scale=0.82),
                ),
                h_pct=0.072,
                spread="justificado",
            ),
        ),
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


def _scrim(size: tuple[int, int], band: int, alpha: int) -> Image.Image:
    """Capa negra que va de transparente (arriba) a `alpha` (abajo del todo),
    de `band` px de alto. Es lo que hace que los logos blancos se lean sobre
    cualquier fondo sin taparle la foto al corredor."""
    w, h = size
    band = max(1, min(band, h))
    grad = Image.new("L", (1, band))
    for y in range(band):
        t = y / (band - 1) if band > 1 else 1.0
        grad.putpixel((0, y), round(alpha * (t**1.2)))
    black = Image.new("RGBA", (w, band), (0, 0, 0, 255))
    black.putalpha(grad.resize((w, band)))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.paste(black, (0, h - band))
    return layer


def _row_pieces(row: LogoRow, short: int, escala: float = 1.0) -> list[Image.Image]:
    """Los logos de una fila ya escalados al alto que les toca."""
    target = max(1, round(short * row.h_pct * escala))
    pieces = []
    for spec in row.logos:
        logo = _load_logo(spec.filename)
        hh = max(1, round(target * spec.scale))
        ww = max(1, round(hh * logo.width / logo.height))
        pieces.append(logo.resize((ww, hh), Image.Resampling.LANCZOS))
    return pieces


def _row_positions(
    pieces: list[Image.Image], w: int, margin: int, gap: int, spread: str
) -> list[int]:
    """Los x de cada logo de la fila."""
    total = sum(p.width for p in pieces)
    if spread == "centrado":
        ancho = total + gap * (len(pieces) - 1)
        x = (w - ancho) // 2
    else:  # justificado: del margen izquierdo al derecho, con aire igual en medio
        usable = w - 2 * margin
        if len(pieces) > 1:
            gap = max(0, (usable - total) // (len(pieces) - 1))
        x = margin
    xs = []
    for piece in pieces:
        xs.append(x)
        x += piece.width + gap
    return xs


def _apply_stacked(base: Image.Image, cfg: StackedTemplate) -> Image.Image:
    """Filas de logos apiladas abajo, sobre el degradado."""
    w, h = base.size
    short = min(w, h)
    horizontal = w >= h
    escala = cfg.landscape_scale if horizontal else 1.0
    margin = round(w * (cfg.landscape_margin_x_pct if horizontal else cfg.margin_x_pct))
    center_gap = round(w * cfg.center_gap_pct)
    row_gap = round(short * cfg.row_gap_pct)
    bottom = round(short * cfg.bottom_pct)

    # Se arma de abajo hacia arriba: primero se sabe cuánto ocupa todo (para el
    # degradado), después se pega cada fila.
    filas = [_row_pieces(row, short, escala) for row in cfg.rows]
    altos = [max(p.height for p in fila) for fila in filas]
    bloque = bottom + sum(altos) + row_gap * (len(filas) - 1)
    base.alpha_composite(_scrim((w, h), round(bloque * cfg.scrim_factor), cfg.scrim_alpha))

    y = h - bottom  # borde de abajo de la fila más baja
    filas_abajo_arriba = zip(reversed(cfg.rows), reversed(filas), reversed(altos), strict=True)
    for row, pieces, alto in filas_abajo_arriba:
        xs = _row_positions(pieces, w, margin, center_gap, row.spread)
        for piece, x in zip(pieces, xs, strict=True):
            base.alpha_composite(piece, (x, y - piece.height))
        y -= alto + row_gap
    return base


def _apply_corners(base: Image.Image, cfg: CornersTemplate) -> Image.Image:
    """Los 2 logos en las esquinas de abajo, con sombra suave."""
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
    return base


def apply_brand_overlay(img: Image.Image, template: str) -> Image.Image:
    """Devuelve una copia RGB de `img` con los logos del template pegados abajo.
    Si el template no existe, devuelve la imagen tal cual (RGB)."""
    cfg = TEMPLATES.get(template)
    if cfg is None:
        return img.convert("RGB")

    base = img.convert("RGBA")
    if isinstance(cfg, StackedTemplate):
        base = _apply_stacked(base, cfg)
    else:
        base = _apply_corners(base, cfg)
    return base.convert("RGB")

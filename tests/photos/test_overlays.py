"""Tests del overlay de logos de marca por evento (Surf City)."""

from __future__ import annotations

import pytest
from PIL import Image

from apps.photos import overlays


def _solid(w: int = 900, h: int = 600, color: tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


# ---------------------------------------------------------------------------
# Assets + template registry
# ---------------------------------------------------------------------------
def test_assets_exist_and_load_rgba() -> None:
    for name in ("surf_city_left.png", "elsalvador_right.png"):
        assert (overlays.OVERLAY_DIR / name).exists(), f"falta el asset {name}"
    assert overlays._load_logo("surf_city_left.png").mode == "RGBA"
    assert overlays._load_logo("elsalvador_right.png").mode == "RGBA"


def test_is_valid_template() -> None:
    assert overlays.is_valid_template("surf_city")
    assert not overlays.is_valid_template("")
    assert not overlays.is_valid_template("bogus")


# ---------------------------------------------------------------------------
# apply_brand_overlay
# ---------------------------------------------------------------------------
def test_apply_brand_overlay_returns_rgb_same_size() -> None:
    out = overlays.apply_brand_overlay(_solid(1000, 700), "surf_city")
    assert out.mode == "RGB"
    assert out.size == (1000, 700)


def _has_bright(img: Image.Image, x0: int, x1: int, y0: int, y1: int) -> bool:
    for x in range(x0, x1, 6):
        for y in range(y0, y1, 6):
            r, g, b = img.getpixel((x, y))
            if r > 180 and g > 180 and b > 180:
                return True
    return False


def test_apply_brand_overlay_marks_both_bottom_corners() -> None:
    """Los 2 logos blancos aparecen en las esquinas de abajo; el centro-arriba
    (fondo negro) queda intacto."""
    out = overlays.apply_brand_overlay(_solid(1200, 800, (0, 0, 0)), "surf_city")
    w, h = out.size
    assert _has_bright(out, 0, w // 3, h * 3 // 4, h)        # abajo-izquierda
    assert _has_bright(out, w * 2 // 3, w, h * 3 // 4, h)    # abajo-derecha
    assert out.getpixel((w // 2, h // 4)) == (0, 0, 0)       # centro-arriba intacto


def test_apply_brand_overlay_works_portrait_and_landscape() -> None:
    """Aspecto-agnóstico: funciona en horizontal y vertical sin romperse."""
    for size in ((1600, 1000), (1000, 1600)):
        out = overlays.apply_brand_overlay(_solid(*size, (0, 0, 0)), "surf_city")
        assert out.size == size
        w, h = size
        assert _has_bright(out, 0, w // 3, h * 3 // 4, h)


def test_invalid_template_returns_unchanged() -> None:
    out = overlays.apply_brand_overlay(_solid(500, 500, (10, 20, 30)), "bogus")
    assert out.mode == "RGB"
    assert out.getpixel((250, 250)) == (10, 20, 30)
    assert out.getpixel((20, 480)) == (10, 20, 30)  # sin logos en la esquina


# ---------------------------------------------------------------------------
# Gating en el pipeline (_try_brand_overlay)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_try_brand_overlay_gated_by_event_flag() -> None:
    from apps.photos.imaging import _try_brand_overlay
    from tests.factories import EventFactory, PhotoFactory

    base = _solid(800, 600)

    photo_on = PhotoFactory(event=EventFactory(brand_overlay="surf_city"))
    out = _try_brand_overlay(base, photo_on)
    assert out is not None
    assert out.size == (800, 600)

    photo_off = PhotoFactory(event=EventFactory(brand_overlay=""))
    assert _try_brand_overlay(base, photo_off) is None


@pytest.mark.django_db
def test_try_brand_overlay_invalid_template_falls_back() -> None:
    """Un template inexistente NO aplica overlay (cae al watermark)."""
    from apps.photos.imaging import _try_brand_overlay
    from tests.factories import EventFactory, PhotoFactory

    photo = PhotoFactory(event=EventFactory(brand_overlay="no_existe"))
    assert _try_brand_overlay(_solid(400, 400), photo) is None

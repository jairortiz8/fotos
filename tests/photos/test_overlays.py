"""Tests del overlay de logos de marca por evento (Surf City)."""

from __future__ import annotations

from io import BytesIO

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
    assert _has_bright(out, 0, w // 3, h * 3 // 4, h)  # abajo-izquierda
    assert _has_bright(out, w * 2 // 3, w, h * 3 // 4, h)  # abajo-derecha
    assert out.getpixel((w // 2, h // 4)) == (0, 0, 0)  # centro-arriba intacto


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


# ---------------------------------------------------------------------------
# Original con logos para DESCARGA (generate_branded_original + download_key)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_generate_branded_original_none_without_overlay() -> None:
    """Evento normal → no genera versión con logos (ni abre la imagen)."""
    from apps.photos.imaging import generate_branded_original
    from tests.factories import EventFactory, PhotoFactory

    photo = PhotoFactory(event=EventFactory(brand_overlay=""))
    assert generate_branded_original(photo, img_object=_solid(400, 400)) is None


@pytest.mark.django_db
def test_generate_branded_original_creates_jpeg_with_logos() -> None:
    """Evento Surf City → sube a R2 un JPEG full-res con los logos en las
    esquinas de abajo, y devuelve su key (.jpg)."""
    import boto3
    from django.test import override_settings
    from moto import mock_aws

    from apps.photos import storage as storage_module
    from apps.photos.imaging import generate_branded_original
    from tests.factories import EventFactory, PhotoFactory

    with override_settings(
        R2_ENDPOINT_URL="",
        R2_ACCESS_KEY_ID="AKIA-TEST",
        R2_SECRET_ACCESS_KEY="SECRET-TEST",
        R2_BUCKET_NAME="test-bucket",
    ):
        storage_module.reset_default_storage_for_tests()
        with mock_aws():
            client = boto3.client(
                "s3",
                aws_access_key_id="AKIA-TEST",
                aws_secret_access_key="SECRET-TEST",
                region_name="us-east-1",
            )
            client.create_bucket(Bucket="test-bucket")

            photo = PhotoFactory(
                event=EventFactory(slug="sc", brand_overlay="surf_city"),
                original_key="events/sc/originals/x.jpg",
            )
            key = generate_branded_original(photo, img_object=_solid(1600, 1000, (0, 0, 0)))

            assert key is not None
            assert key.endswith(".jpg")
            body = client.get_object(Bucket="test-bucket", Key=key)["Body"].read()
            im = Image.open(BytesIO(body))
            assert im.format == "JPEG"
            # FULL-RES: la descarga es el original a resolución completa (NO el
            # preview de 1200px). Un downscale accidental rompería la feature.
            assert im.size == (1600, 1000)
            rgb = im.convert("RGB")
            w, h = rgb.size
            assert _has_bright(rgb, 0, w // 3, h * 3 // 4, h)  # logo abajo-izq
            assert _has_bright(rgb, w * 2 // 3, w, h * 3 // 4, h)  # logo abajo-der
        storage_module.reset_default_storage_for_tests()


@pytest.mark.django_db
def test_download_key_selects_branded_only_for_branded_event() -> None:
    """`download_key()` = branded sólo si el evento tiene overlay Y hay branded_key;
    si no, el original limpio."""
    from tests.factories import EventFactory, PhotoFactory

    branded_evt = EventFactory(brand_overlay="surf_city")
    p_ok = PhotoFactory(event=branded_evt, original_key="o1", branded_key="b1")
    assert p_ok.download_key() == "b1"

    p_no_branded = PhotoFactory(event=branded_evt, original_key="o2", branded_key="")
    assert p_no_branded.download_key() == "o2"

    p_plain = PhotoFactory(
        event=EventFactory(brand_overlay=""), original_key="o3", branded_key="b3"
    )
    assert p_plain.download_key() == "o3"

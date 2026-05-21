"""Tests de imaging: preview con watermark + thumbnail + EXIF parsing."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from apps.ml.synthetic import write_synthetic_jpeg
from apps.photos import storage as storage_module
from apps.photos.imaging import (
    PREVIEW_LONG_EDGE,
    THUMB_LONG_EDGE,
    apply_diagonal_watermark,
    extract_exif_and_dimensions,
    generate_preview,
    generate_thumbnail,
)
from apps.photos.storage import R2Storage
from tests.factories import EventFactory, PhotoFactory

BUCKET = "test-bucket"


@pytest.fixture
def storage(settings):  # type: ignore[no-untyped-def]
    """R2Storage en mock + bucket pre-creado."""
    settings.R2_ENDPOINT_URL = ""  # moto-friendly
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    storage_module.reset_default_storage_for_tests()

    with mock_aws():
        boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        ).create_bucket(Bucket=BUCKET)
        yield R2Storage()

    storage_module.reset_default_storage_for_tests()


@pytest.fixture
def synthetic_jpeg(tmp_path: Path) -> Path:
    return write_synthetic_jpeg("1234", target=tmp_path / "test.jpg")


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------
def test_apply_diagonal_watermark_returns_rgb_image() -> None:
    base = Image.new("RGB", (800, 1200), (40, 40, 45))
    out = apply_diagonal_watermark(base, "RUNFOTO · TEST")
    assert out.mode == "RGB"
    assert out.size == (800, 1200)


def test_apply_diagonal_watermark_changes_pixels() -> None:
    """El output debe diferir del input (la marca debe ser visible al menos en un pixel)."""
    base = Image.new("RGB", (400, 600), (0, 0, 0))
    out = apply_diagonal_watermark(base, "WATERMARK")
    diff_pixel_count = 0
    for x in range(0, 400, 8):
        for y in range(0, 600, 8):
            if out.getpixel((x, y)) != (0, 0, 0):
                diff_pixel_count += 1
    assert diff_pixel_count > 10  # hay algo escrito en muchas posiciones


# ---------------------------------------------------------------------------
# Preview / thumbnail
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_generate_preview_resizes_to_1200_long_edge(
    storage: R2Storage, synthetic_jpeg: Path
) -> None:
    event = EventFactory(slug="test-event")
    photo = PhotoFactory(event=event, original_key=f"events/{event.slug}/originals/abc123.jpg")

    key = generate_preview(photo, synthetic_jpeg, storage=storage)
    assert key.startswith(f"events/{event.slug}/previews/")
    assert key.endswith(".webp")

    # Descargar y verificar dimensiones
    buf = BytesIO()
    storage.download_fileobj(key, buf)
    buf.seek(0)
    with Image.open(buf) as img:
        long_edge = max(img.size)
        assert long_edge <= PREVIEW_LONG_EDGE
        assert long_edge == PREVIEW_LONG_EDGE or img.size[0] == img.size[1]


@pytest.mark.django_db
def test_generate_thumbnail_resizes_to_400_long_edge(
    storage: R2Storage, synthetic_jpeg: Path
) -> None:
    event = EventFactory(slug="test-event-thumb")
    photo = PhotoFactory(event=event, original_key=f"events/{event.slug}/originals/xyz789.jpg")

    key = generate_thumbnail(photo, synthetic_jpeg, storage=storage)
    assert key.endswith(".webp")

    buf = BytesIO()
    storage.download_fileobj(key, buf)
    buf.seek(0)
    with Image.open(buf) as img:
        assert max(img.size) <= THUMB_LONG_EDGE


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_extract_exif_sets_dimensions(synthetic_jpeg: Path) -> None:
    event = EventFactory()
    photo = PhotoFactory(event=event)
    extract_exif_and_dimensions(photo, synthetic_jpeg)
    assert photo.width > 0
    assert photo.height > 0
    # Imagen sintética sin EXIF → todos vacíos.
    assert photo.camera_make == ""
    assert photo.iso is None


@pytest.mark.django_db
def test_extract_exif_handles_image_without_exif(tmp_path: Path) -> None:
    """Imagen sin EXIF debe poblar solo width/height, sin romper."""
    img_path = tmp_path / "blank.jpg"
    Image.new("RGB", (640, 480), (128, 128, 128)).save(img_path, format="JPEG")

    event = EventFactory()
    photo = PhotoFactory(event=event)
    extract_exif_and_dimensions(photo, img_path)
    assert photo.width == 640
    assert photo.height == 480
    assert photo.exif_raw == {}


# ---------------------------------------------------------------------------
# Helpers de formato EXIF (focal, apertura, shutter)
# ---------------------------------------------------------------------------
def test_format_focal_handles_int_and_float() -> None:
    from apps.photos.imaging import _format_focal

    assert _format_focal(200) == "200mm"
    assert _format_focal(85.5) == "86mm"
    assert _format_focal(None) == ""
    assert _format_focal("invalid") == ""


def test_format_aperture() -> None:
    from apps.photos.imaging import _format_aperture

    assert _format_aperture(2.8) == "f/2.8"
    assert _format_aperture(4) == "f/4"
    assert _format_aperture(None) == ""


def test_format_shutter_fast() -> None:
    from apps.photos.imaging import _format_shutter

    # 1/2000s ≈ 0.0005s
    assert _format_shutter(1 / 2000) == "1/2000s"


def test_format_shutter_slow() -> None:
    from apps.photos.imaging import _format_shutter

    assert _format_shutter(2.0) == "2s"


def test_format_shutter_none() -> None:
    from apps.photos.imaging import _format_shutter

    assert _format_shutter(None) == ""


def test_safe_int_helper() -> None:
    from apps.photos.imaging import _safe_int

    assert _safe_int(400) == 400
    assert _safe_int("800") == 800
    assert _safe_int(None) is None
    assert _safe_int("not a number") is None


def test_parse_capture_time_valid() -> None:
    """EXIF guarda fechas tipo `'2026:05:14 09:23:11'`."""
    from apps.photos.imaging import _parse_capture_time

    dt = _parse_capture_time({"DateTimeOriginal": "2026:05:14 09:23:11"})
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 14


def test_parse_capture_time_invalid_string() -> None:
    from apps.photos.imaging import _parse_capture_time

    assert _parse_capture_time({"DateTimeOriginal": "not-a-date"}) is None


def test_parse_capture_time_no_field() -> None:
    from apps.photos.imaging import _parse_capture_time

    assert _parse_capture_time({}) is None


def test_make_json_safe_handles_bytes() -> None:
    from apps.photos.imaging import _make_json_safe

    assert _make_json_safe(b"hello") == "hello"
    assert _make_json_safe(123) == 123
    assert _make_json_safe(None) is None

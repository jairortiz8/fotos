"""Visor de caras: filtro de calidad, recorte, avatar y búsqueda por cara."""

from __future__ import annotations

from io import BytesIO

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws
from PIL import Image

from apps.events.models import EventStatus
from apps.photos import storage as storage_module
from apps.photos.faces import face_size_px, generate_avatars_for_photo, is_avatar_sized
from apps.photos.imaging import FaceTooBlurryError, _square_face_box, generate_face_avatar
from apps.photos.models import FaceEmbedding
from tests.factories import ApprovedPhotoFactory, EventFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    storage_module.reset_default_storage_for_tests()
    cache.clear()
    with mock_aws():
        client = boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client
    storage_module.reset_default_storage_for_tests()
    cache.clear()


def _sharp_photo_bytes(w: int = 900, h: int = 600) -> bytes:
    """JPEG con bordes duros (alto contraste) → pasa el umbral de nitidez."""
    img = Image.new("RGB", (w, h), "white")
    px = img.load()
    assert px is not None
    for x in range(w):
        for y in range(h):
            if (x // 6 + y // 6) % 2 == 0:
                px[x, y] = (10, 10, 10)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _flat_photo_bytes(w: int = 900, h: int = 600) -> bytes:
    """JPEG liso (sin detalle) → NO pasa el umbral de nitidez."""
    buf = BytesIO()
    Image.new("RGB", (w, h), (128, 128, 130)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# --- filtro de tamaño -------------------------------------------------------
def test_face_size_px_uses_larger_side() -> None:
    assert face_size_px({"x1": 0, "y1": 0, "x2": 100, "y2": 40}) == 100
    assert face_size_px({}) == 0.0
    assert face_size_px(None) == 0.0


def test_is_avatar_sized_rejects_small_faces() -> None:
    """Una cara del fondo (chiquita) no se convierte en avatar."""
    big = {"x1": 0, "y1": 0, "x2": 200, "y2": 200}
    small = {"x1": 0, "y1": 0, "x2": 30, "y2": 30}
    assert is_avatar_sized(big) is True
    assert is_avatar_sized(small) is False


# --- recorte ----------------------------------------------------------------
def test_square_face_box_is_square_and_inside_image() -> None:
    left, top, right, bottom = _square_face_box({"x1": 10, "y1": 20, "x2": 60, "y2": 90}, 800, 600)
    assert right - left == bottom - top  # cuadrado
    assert left >= 0 and top >= 0
    assert right <= 800 and bottom <= 600


def test_square_face_box_clamps_face_at_the_edge() -> None:
    """Cara pegada al borde: la caja se corre adentro en vez de salirse."""
    left, top, right, bottom = _square_face_box({"x1": 0, "y1": 0, "x2": 40, "y2": 40}, 300, 300)
    assert left >= 0 and top >= 0
    assert right <= 300 and bottom <= 300


def test_generate_face_avatar_returns_square_webp() -> None:
    data = generate_face_avatar(_sharp_photo_bytes(), {"x1": 100, "y1": 100, "x2": 300, "y2": 300})
    img = Image.open(BytesIO(data))
    assert img.format == "WEBP"
    assert img.width == img.height == 160


def test_generate_face_avatar_rejects_blurry_crop() -> None:
    """Una cara sin detalle (fondo desenfocado) no genera avatar."""
    with pytest.raises(FaceTooBlurryError):
        generate_face_avatar(_flat_photo_bytes(), {"x1": 100, "y1": 100, "x2": 300, "y2": 300})


# --- batch por foto ---------------------------------------------------------
@pytest.mark.django_db
def test_generate_avatars_for_photo_skips_small_and_keeps_big(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    big = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    small = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 10, "y1": 10, "x2": 40, "y2": 40}
    )

    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 1
    assert stats["too_small"] == 1

    big.refresh_from_db()
    small.refresh_from_db()
    assert big.avatar_key != ""
    assert small.avatar_key == ""


@pytest.mark.django_db
def test_generate_avatars_for_photo_is_idempotent(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )

    assert generate_avatars_for_photo(photo)["generated"] == 1
    assert generate_avatars_for_photo(photo)["generated"] == 0  # ya estaba


# --- vistas -----------------------------------------------------------------
@pytest.mark.django_db
def test_face_avatar_view_serves_webp(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    generate_avatars_for_photo(photo)

    resp = Client().get(
        reverse("events:face_avatar", kwargs={"slug": event.slug, "face_id": face.id})
    )
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/webp"
    assert "max-age" in resp["Cache-Control"]


@pytest.mark.django_db
def test_face_avatar_view_404_without_avatar(r2) -> None:  # type: ignore[no-untyped-def]
    """Una cara que no calificó (sin avatar_key) no se sirve."""
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/x.jpg")
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 0, "y1": 0, "x2": 20, "y2": 20}
    )
    resp = Client().get(
        reverse("events:face_avatar", kwargs={"slug": event.slug, "face_id": face.id})
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_lightbox_shows_visor_only_for_faces_with_avatar(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    big = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    small = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 5, "y1": 5, "x2": 30, "y2": 30}
    )
    generate_avatars_for_photo(photo)

    resp = Client().get(
        reverse("events:lightbox", kwargs={"slug": event.slug, "photo_id": photo.id})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?cara={big.id}" in body
    assert f"?cara={small.id}" not in body  # la chica no entra al visor


@pytest.mark.django_db
def test_gallery_face_search_returns_that_person(r2) -> None:  # type: ignore[no-untyped-def]
    """?cara=<id> devuelve las fotos parecidas usando el embedding guardado."""
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    other = ApprovedPhotoFactory(event=event, original_key="events/e/originals/otra.jpg")

    vec = [0.0] * 512
    vec[0] = 1.0
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=vec, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    # Misma persona en otra foto (vector idéntico) → tiene que aparecer.
    FaceEmbedding.objects.create(
        photo=other, embedding=vec, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    # Persona distinta (vector ortogonal) → NO tiene que aparecer.
    far = [0.0] * 512
    far[1] = 1.0
    third = ApprovedPhotoFactory(event=event, original_key="events/e/originals/tercera.jpg")
    FaceEmbedding.objects.create(
        photo=third, embedding=far, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )

    resp = Client().get(
        reverse("events:gallery", kwargs={"slug": event.slug}), {"cara": str(face.id)}
    )
    assert resp.status_code == 200
    ids = {p.id for p in resp.context["search_photos"]}
    assert {photo.id, other.id} <= ids
    assert third.id not in ids

"""Tests de la descarga de UNA foto: sirve el ORIGINAL (alta resolución, sin
watermark) como ARCHIVO (Content-Disposition: attachment), same-origin, para que
baje como descarga y no se abra como página (iOS/Safari)."""

from __future__ import annotations

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.events.models import EventStatus, EventVisibility
from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photos import storage as storage_module
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, EventFactory, PhotoFactory

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


def _body(resp) -> bytes:  # type: ignore[no-untyped-def]
    return b"".join(resp.streaming_content)


@pytest.mark.django_db
def test_download_serves_original_as_attachment(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    key = "events/e/originals/foto.jpg"
    data = synthetic_jpeg_bytes("123")
    r2.put_object(Bucket=BUCKET, Key=key, Body=data)
    photo = ApprovedPhotoFactory(event=event, original_key=key, original_filename="DSC_1.jpg")

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))

    assert resp.status_code == 200
    # Se baja como ARCHIVO (no se abre como página) con el nombre original.
    assert resp["Content-Disposition"].startswith("attachment")
    assert "DSC_1.jpg" in resp["Content-Disposition"]
    assert resp["Content-Type"] == "image/jpeg"
    # El cuerpo es el ORIGINAL exacto (no el preview/thumbnail).
    assert _body(resp) == data


@pytest.mark.django_db
def test_download_increments_counters(r2) -> None:  # type: ignore[no-untyped-def]
    """Cada descarga exitosa suma al contador de la foto y al total del evento
    (lo que alimenta la tarjeta "Descargas" del dashboard)."""
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    key = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes("123"))
    photo = ApprovedPhotoFactory(event=event, original_key=key)

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 200
    photo.refresh_from_db()
    event.refresh_from_db()
    assert photo.download_count == 1
    assert event.download_count == 1


@pytest.mark.django_db
def test_download_filename_gets_jpg_extension(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    key = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes("1"))
    photo = ApprovedPhotoFactory(event=event, original_key=key, original_filename="sin_extension")

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert "sin_extension.jpg" in resp["Content-Disposition"]


@pytest.mark.django_db
def test_download_404_for_non_approved(r2) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(status=PhotoStatus.PENDING_REVIEW)
    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_404_for_private_event(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PRIVATE)
    photo = ApprovedPhotoFactory(event=event)
    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Descarga con logos (eventos brandeados, ej. Surf City)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_download_serves_branded_when_event_branded(r2) -> None:  # type: ignore[no-untyped-def]
    """En un evento con `brand_overlay`, la descarga sirve el original CON logos
    (branded_key), NO el original limpio — para que el archivo bajado los lleve."""
    event = EventFactory(
        status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC, brand_overlay="surf_city"
    )
    okey = "events/e/originals/foto.jpg"
    bkey = "events/e/branded/foto.jpg"
    original = synthetic_jpeg_bytes("111")
    branded = synthetic_jpeg_bytes("999")  # bytes distintos → distinguible del limpio
    r2.put_object(Bucket=BUCKET, Key=okey, Body=original)
    r2.put_object(Bucket=BUCKET, Key=bkey, Body=branded)
    photo = ApprovedPhotoFactory(
        event=event, original_key=okey, branded_key=bkey, original_filename="DSC_1.jpg"
    )

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")
    assert resp["Content-Type"] == "image/jpeg"
    assert _body(resp) == branded  # el con logos, no el limpio


@pytest.mark.django_db
def test_download_falls_back_to_original_when_branded_missing(r2) -> None:  # type: ignore[no-untyped-def]
    """Evento brandeado pero foto aún sin `branded_key` (vieja / no reprocesada):
    la descarga NO rompe — cae al original limpio."""
    event = EventFactory(
        status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC, brand_overlay="surf_city"
    )
    okey = "events/e/originals/foto.jpg"
    original = synthetic_jpeg_bytes("111")
    r2.put_object(Bucket=BUCKET, Key=okey, Body=original)
    photo = ApprovedPhotoFactory(event=event, original_key=okey, branded_key="")

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 200
    assert _body(resp) == original


@pytest.mark.django_db
def test_download_ignores_branded_key_when_event_not_branded(r2) -> None:  # type: ignore[no-untyped-def]
    """Sin `brand_overlay` en el evento, se sirve el original limpio aunque la
    foto tenga un branded_key colgado (defensa: no filtrar logos por accidente)."""
    event = EventFactory(
        status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC, brand_overlay=""
    )
    okey = "events/e/originals/foto.jpg"
    bkey = "events/e/branded/foto.jpg"
    original = synthetic_jpeg_bytes("111")
    r2.put_object(Bucket=BUCKET, Key=okey, Body=original)
    r2.put_object(Bucket=BUCKET, Key=bkey, Body=synthetic_jpeg_bytes("999"))
    photo = ApprovedPhotoFactory(event=event, original_key=okey, branded_key=bkey)

    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 200
    assert _body(resp) == original

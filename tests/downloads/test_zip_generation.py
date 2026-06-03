"""Tests de generación de ZIP (con moto para R2)."""

from __future__ import annotations

import io
import zipfile

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.downloads.models import ZipDownload, ZipStatus
from apps.downloads.tasks import generate_zip
from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photos import storage as storage_module
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, EventFactory, PhotoFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2_with_photos(settings):  # type: ignore[no-untyped-def]
    """R2 mockeado + 3 fotos aprobadas con originales subidos."""
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

        event = EventFactory(slug="zip-event")
        photos = []
        for i in range(3):
            key = f"events/zip-event/originals/p{i}.jpg"
            client.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes(str(1000 + i)))
            photo = ApprovedPhotoFactory(
                event=event, original_key=key, original_filename=f"DSC_{i}.jpg"
            )
            photos.append(photo)

        yield event, photos

    storage_module.reset_default_storage_for_tests()
    cache.clear()


@pytest.mark.django_db
def test_zip_contains_all_selected_originals(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    _event, photos = r2_with_photos
    download = ZipDownload.objects.create(
        requester_ip_hash="x", photo_ids=[p.id for p in photos], photo_count=3
    )
    generate_zip.apply(args=[download.id]).get()
    download.refresh_from_db()
    assert download.status == ZipStatus.READY
    assert download.zip_key

    # Descargar el ZIP de R2 y verificar contenido.
    storage = storage_module.default_storage()
    buf = io.BytesIO()
    storage.download_fileobj(download.zip_key, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
    assert len(names) == 3
    assert "DSC_0.jpg" in names


@pytest.mark.django_db
def test_zip_excludes_non_approved_photos(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    event, photos = r2_with_photos
    pending = PhotoFactory(event=event, status=PhotoStatus.PENDING_REVIEW)
    download = ZipDownload.objects.create(
        requester_ip_hash="x",
        photo_ids=[photos[0].id, pending.id],
        photo_count=2,
    )
    generate_zip.apply(args=[download.id]).get()
    download.refresh_from_db()

    storage = storage_module.default_storage()
    buf = io.BytesIO()
    storage.download_fileobj(download.zip_key, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
    assert len(names) == 1  # solo la aprobada


@pytest.mark.django_db
def test_zip_sets_expiry(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    _event, photos = r2_with_photos
    download = ZipDownload.objects.create(
        requester_ip_hash="x", photo_ids=[photos[0].id], photo_count=1
    )
    generate_zip.apply(args=[download.id]).get()
    download.refresh_from_db()
    assert download.expires_at is not None
    assert download.download_url


# ---------------------------------------------------------------------------
# View: CreateZipDownloadView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_create_zip_view_rate_limit_5_per_hour(r2_with_photos, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from unittest.mock import patch

    _event, photos = r2_with_photos
    url = reverse("downloads:create")
    ids = ",".join(str(p.id) for p in photos)

    with patch("apps.downloads.tasks.generate_zip.delay"):
        client = Client()
        last = 200
        for _ in range(7):
            r = client.post(url, {"ids": ids}, REMOTE_ADDR="7.7.7.7")
            last = r.status_code
            if last == 429:
                break
    assert last == 429


@pytest.mark.django_db
def test_create_zip_view_max_200(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    url = reverse("downloads:create")
    ids = ",".join(str(i) for i in range(201))
    client = Client()
    r = client.post(url, {"ids": ids}, REMOTE_ADDR="6.6.6.6")
    assert r.status_code == 400
    assert r.json()["error"] == "too_many"


@pytest.mark.django_db
def test_create_zip_view_empty_selection(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    url = reverse("downloads:create")
    client = Client()
    r = client.post(url, {"ids": ""}, REMOTE_ADDR="5.5.5.5")
    assert r.status_code == 400


@pytest.mark.django_db
def test_zip_status_polling_endpoint(r2_with_photos) -> None:  # type: ignore[no-untyped-def]
    _event, photos = r2_with_photos
    download = ZipDownload.objects.create(
        requester_ip_hash="x", photo_ids=[photos[0].id], photo_count=1, status=ZipStatus.PENDING
    )
    client = Client()
    r = client.get(reverse("downloads:status", args=[download.id]))
    assert r.status_code == 200
    assert r.json()["status"] == ZipStatus.PENDING

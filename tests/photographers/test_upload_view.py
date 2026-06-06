"""Tests del PhotographerUploadView."""

from __future__ import annotations

from unittest.mock import patch

import boto3
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photographers.models import PhotographerLink
from apps.photos import storage as storage_module
from apps.photos.models import Photo, PhotoStatus
from tests.factories import EventFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2_bucket(settings):  # type: ignore[no-untyped-def]
    """Bucket S3 mockeado con moto + R2 settings."""
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
        yield
    storage_module.reset_default_storage_for_tests()


@pytest.fixture
def link_token() -> tuple[PhotographerLink, str]:
    event = EventFactory()
    return PhotographerLink.generate_token_and_create(event, name="Foto")


@pytest.fixture(autouse=True)
def no_celery_dispatch():
    """Evita que `process_photo.delay` dispare un task real durante tests."""
    with patch("apps.photos.tasks.process_photo.delay") as m:
        yield m


def _jpeg_upload(name: str = "shot.jpg", number: str = "1042") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name=name,
        content=synthetic_jpeg_bytes(number, width=600, height=900),
        content_type="image/jpeg",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_upload_valid_jpeg_creates_photo(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])

    response = client.post(url, {"file": _jpeg_upload()})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == PhotoStatus.PROCESSING

    photo = Photo.objects.get(id=payload["id"])
    assert photo.event_id == link.event_id
    assert photo.photographer_link_id == link.id
    assert photo.original_key.startswith(f"events/{link.event.slug}/originals/")
    assert photo.original_key.endswith(".jpg")


@pytest.mark.django_db
def test_upload_dispatches_process_task(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    _link, raw_token = link_token
    client.post(reverse("photographer:upload", args=[raw_token]), {"file": _jpeg_upload()})
    assert no_celery_dispatch.called


@pytest.mark.django_db
def test_upload_increments_photos_uploaded(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])
    client.post(url, {"file": _jpeg_upload("a.jpg")})
    client.post(url, {"file": _jpeg_upload("b.jpg")})
    link.refresh_from_db()
    assert link.photos_uploaded == 2


@pytest.mark.django_db
def test_upload_creates_audit_log(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    from apps.core.models import AuditLog

    AuditLog.objects.all().delete()
    _link, raw_token = link_token
    client.post(reverse("photographer:upload", args=[raw_token]), {"file": _jpeg_upload()})
    assert AuditLog.objects.filter(action="photo.uploaded").exists()


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_upload_rejects_non_jpeg(client: Client, link_token, r2_bucket) -> None:
    _link, raw_token = link_token
    fake = SimpleUploadedFile("not-a-photo.png", content=b"\x89PNG\r\n", content_type="image/png")
    response = client.post(reverse("photographer:upload", args=[raw_token]), {"file": fake})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_format"


@pytest.mark.django_db
def test_upload_converts_heic_to_jpeg(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    """Una HEIC real (iPhone/Mac) se acepta y se convierte a JPEG (no se descarta)."""
    import io

    from PIL import Image

    import apps.photos.imaging  # noqa: F401  (registra el opener HEIF al importar)

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (100, 50, 25)).save(buf, format="HEIF")
    heic = SimpleUploadedFile("iphone.heic", content=buf.getvalue(), content_type="image/heic")

    _link, raw_token = link_token
    response = client.post(reverse("photographer:upload", args=[raw_token]), {"file": heic})
    assert response.status_code == 200
    photo = Photo.objects.get(id=response.json()["id"])
    assert photo.original_key.endswith(".jpg")


@pytest.mark.django_db
def test_upload_rejects_oversize_file(client: Client, link_token, r2_bucket, settings) -> None:
    settings.PHOTO_UPLOAD_MAX_BYTES = 1024  # 1 KB para forzar el rechazo
    _link, raw_token = link_token
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "file_too_large"


@pytest.mark.django_db
def test_upload_rejects_when_photo_limit_reached(client: Client, link_token, r2_bucket) -> None:
    link, raw_token = link_token
    link.photo_limit = 5
    link.photos_uploaded = 5
    link.save()
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_upload_returns_410_for_invalid_token(client: Client, r2_bucket) -> None:
    response = client.post(
        reverse("photographer:upload", args=["definitely-not-valid"]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 410


@pytest.mark.django_db
def test_upload_returns_503_when_r2_not_configured(
    client: Client, link_token, settings, no_celery_dispatch
) -> None:
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = ""
    settings.R2_SECRET_ACCESS_KEY = ""
    settings.R2_BUCKET_NAME = ""
    storage_module.reset_default_storage_for_tests()

    _link, raw_token = link_token
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "storage_not_configured"


@pytest.mark.django_db
def test_upload_no_file_returns_400(client: Client, link_token, r2_bucket) -> None:
    _link, raw_token = link_token
    response = client.post(reverse("photographer:upload", args=[raw_token]), {})
    assert response.status_code == 400
    assert response.json()["error"] == "no_file"

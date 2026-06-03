"""Tests del modelo Photo (URLs firmadas, contadores, soft delete)."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from apps.photos import storage as storage_module
from apps.photos.models import Photo, PhotoStatus
from tests.factories import PhotoFactory


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    """R2 mockeado con moto para que las signed URLs sean reales."""
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = "test-bucket"
    storage_module.reset_default_storage_for_tests()
    with mock_aws():
        boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        ).create_bucket(Bucket="test-bucket")
        yield
    storage_module.reset_default_storage_for_tests()


@pytest.mark.django_db
def test_get_preview_url_signed_with_expiry(r2) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(preview_key="events/x/previews/foo.webp")
    url = photo.get_preview_url(expires_in_seconds=300)
    # URL firmada real de R2 (S3 v4): contiene la key y el parámetro de expiración.
    assert "events/x/previews/foo.webp" in url
    assert "X-Amz-Expires=300" in url or "Expires=" in url


@pytest.mark.django_db
def test_get_original_url_signed_with_expiry(r2) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(original_key="events/x/originals/bar.jpg")
    url = photo.get_original_url(expires_in_seconds=600)
    assert "events/x/originals/bar.jpg" in url
    assert "X-Amz-Expires=600" in url or "Expires=" in url


@pytest.mark.django_db
def test_get_preview_url_empty_when_key_missing() -> None:
    photo = PhotoFactory(preview_key="")
    assert photo.get_preview_url() == ""


@pytest.mark.django_db
def test_get_preview_url_empty_when_r2_not_configured(settings) -> None:  # type: ignore[no-untyped-def]
    """Sin R2 configurado (tests sin credentials), devuelve '' en vez de romper."""
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = ""
    settings.R2_SECRET_ACCESS_KEY = ""
    settings.R2_BUCKET_NAME = ""
    storage_module.reset_default_storage_for_tests()
    photo = PhotoFactory(preview_key="events/x/previews/foo.webp")
    assert photo.get_preview_url() == ""
    storage_module.reset_default_storage_for_tests()


@pytest.mark.django_db
def test_soft_delete_does_not_remove_from_r2() -> None:
    photo = PhotoFactory()
    original_key = photo.original_key
    photo.soft_delete()
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.DELETED
    assert photo.original_key == original_key  # Sigue en R2 (lo borra retention task)


@pytest.mark.django_db
def test_view_count_increments_atomically() -> None:
    photo = PhotoFactory(view_count=0)
    photo.increment_view_count()
    photo.refresh_from_db()
    assert photo.view_count == 1
    photo.increment_view_count()
    photo.refresh_from_db()
    assert photo.view_count == 2


@pytest.mark.django_db
def test_download_count_increments_atomically() -> None:
    photo = PhotoFactory(download_count=0)
    photo.increment_download_count()
    photo.refresh_from_db()
    assert photo.download_count == 1


@pytest.mark.django_db
def test_mark_approved_sets_timestamp_and_flag() -> None:
    photo = PhotoFactory()
    photo.mark_approved(by_admin=True)
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.APPROVED
    assert photo.approved_at is not None
    assert photo.approved_by_admin is True


@pytest.mark.django_db
def test_photo_original_key_unique() -> None:
    """Dos Photos no pueden compartir `original_key`."""
    from django.db import IntegrityError

    PhotoFactory(original_key="events/x/originals/dup.jpg")
    with pytest.raises(IntegrityError):
        PhotoFactory(original_key="events/x/originals/dup.jpg")


@pytest.mark.django_db
def test_photo_ordering_by_capture_time_desc() -> None:
    import datetime as dt

    from django.utils import timezone

    older = PhotoFactory(capture_time=timezone.now() - dt.timedelta(hours=2))
    newer = PhotoFactory(capture_time=timezone.now())
    qs = list(Photo.objects.all()[:2])
    assert qs[0] == newer
    assert qs[1] == older

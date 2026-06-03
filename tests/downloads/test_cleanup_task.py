"""Tests del cleanup de ZIPs expirados."""

from __future__ import annotations

import datetime as dt

import boto3
import pytest
from django.utils import timezone
from moto import mock_aws

from apps.downloads.models import ZipDownload, ZipStatus
from apps.downloads.tasks import cleanup_expired_zips
from apps.photos import storage as storage_module

BUCKET = "test-bucket"


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    storage_module.reset_default_storage_for_tests()
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


@pytest.mark.django_db
def test_cleanup_marks_status_expired(r2) -> None:  # type: ignore[no-untyped-def]
    r2.put_object(Bucket=BUCKET, Key="events/x/zips/1.zip", Body=b"zip")
    download = ZipDownload.objects.create(
        requester_ip_hash="x",
        photo_ids=[1],
        status=ZipStatus.READY,
        zip_key="events/x/zips/1.zip",
        expires_at=timezone.now() - dt.timedelta(hours=2),
    )
    result = cleanup_expired_zips()
    download.refresh_from_db()
    assert download.status == ZipStatus.EXPIRED
    assert download.zip_key == ""
    assert result["expired"] == 1


@pytest.mark.django_db
def test_cleanup_deletes_from_r2(r2) -> None:  # type: ignore[no-untyped-def]
    r2.put_object(Bucket=BUCKET, Key="events/x/zips/2.zip", Body=b"zip")
    ZipDownload.objects.create(
        requester_ip_hash="x",
        photo_ids=[1],
        status=ZipStatus.READY,
        zip_key="events/x/zips/2.zip",
        expires_at=timezone.now() - dt.timedelta(hours=2),
    )
    cleanup_expired_zips()
    # El objeto ya no existe en R2.
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        r2.head_object(Bucket=BUCKET, Key="events/x/zips/2.zip")


@pytest.mark.django_db
def test_cleanup_ignores_non_expired(r2) -> None:  # type: ignore[no-untyped-def]
    ZipDownload.objects.create(
        requester_ip_hash="x",
        photo_ids=[1],
        status=ZipStatus.READY,
        zip_key="events/x/zips/3.zip",
        expires_at=timezone.now() + dt.timedelta(hours=1),  # futuro
    )
    result = cleanup_expired_zips()
    assert result["expired"] == 0


@pytest.mark.django_db
def test_cleanup_empty_returns_zero(r2) -> None:  # type: ignore[no-untyped-def]
    result = cleanup_expired_zips()
    assert result == {"expired": 0, "deleted_from_r2": 0}

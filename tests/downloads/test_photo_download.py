"""Tests de la descarga de UNA foto: debe bajar el ORIGINAL (alta resolución,
sin watermark), no el preview."""

from __future__ import annotations

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.events.models import EventStatus, EventVisibility
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
    storage_module.reset_default_storage_for_tests()
    cache.clear()
    with mock_aws():
        boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        ).create_bucket(Bucket=BUCKET)
        yield
    storage_module.reset_default_storage_for_tests()
    cache.clear()


@pytest.mark.django_db
def test_download_redirects_to_original_with_attachment(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    photo = ApprovedPhotoFactory(
        event=event, original_key="events/e/originals/foto.jpg", original_filename="DSC_1.jpg"
    )
    resp = Client().get(reverse("downloads:photo", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 302
    assert "originals" in resp.url  # apunta al ORIGINAL (no preview/thumbnail)
    assert "response-content-disposition" in resp.url.lower()  # fuerza la descarga


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

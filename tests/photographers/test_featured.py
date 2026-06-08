"""Tests de la imagen destacada de la carpeta del fotógrafo (subida + serving)."""

from __future__ import annotations

import boto3
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photographers.models import PhotographerLink
from apps.photos import storage as storage_module
from tests.factories import EventFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2_bucket(settings):  # type: ignore[no-untyped-def]
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


@pytest.fixture
def link_token() -> tuple[PhotographerLink, str]:
    return PhotographerLink.generate_token_and_create(EventFactory(), name="Foto")


def _img() -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "destacada.jpg", synthetic_jpeg_bytes("1", width=600, height=400), content_type="image/jpeg"
    )


@pytest.mark.django_db
def test_featured_upload_sets_key_and_uploads(client: Client, link_token, r2_bucket) -> None:  # type: ignore[no-untyped-def]
    link, token = link_token
    resp = client.post(reverse("photographer:featured_upload", args=[token]), {"file": _img()})
    assert resp.status_code == 200
    link.refresh_from_db()
    assert link.featured_image_key == f"photographer_covers/{link.id}.webp"
    obj = r2_bucket.get_object(Bucket=BUCKET, Key=link.featured_image_key)
    assert obj["ContentType"] == "image/webp"
    assert resp.json()["featured_url"]


@pytest.mark.django_db
def test_featured_upload_invalid_link_410(client: Client, r2_bucket) -> None:  # type: ignore[no-untyped-def]
    resp = client.post(reverse("photographer:featured_upload", args=["badtoken"]), {"file": _img()})
    assert resp.status_code == 410


@pytest.mark.django_db
def test_cover_view_serves_webp(client: Client, link_token, r2_bucket) -> None:  # type: ignore[no-untyped-def]
    link, token = link_token
    client.post(reverse("photographer:featured_upload", args=[token]), {"file": _img()})
    resp = client.get(reverse("photographer:cover", kwargs={"link_id": link.id}))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/webp"
    assert "max-age" in resp["Cache-Control"]
    assert b"".join(resp.streaming_content)[:4] == b"RIFF"


@pytest.mark.django_db
def test_cover_view_404_without_featured(client: Client, link_token, r2_bucket) -> None:  # type: ignore[no-untyped-def]
    link, _token = link_token
    resp = client.get(reverse("photographer:cover", kwargs={"link_id": link.id}))
    assert resp.status_code == 404

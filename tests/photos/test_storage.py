"""Tests del R2Storage con moto (mock S3)."""

from __future__ import annotations

from io import BytesIO

import boto3
import pytest
from moto import mock_aws

from apps.photos import storage as storage_module
from apps.photos.storage import (
    R2NotConfiguredError,
    R2Storage,
    R2UploadError,
    key_for_original,
    key_for_preview,
    key_for_thumbnail,
    key_for_zip,
)

BUCKET = "test-bucket"
ENDPOINT = ""  # vacío → boto3 usa default AWS, moto intercepta


@pytest.fixture
def r2(monkeypatch, settings):  # type: ignore[no-untyped-def]
    """R2Storage con moto + credentials de juguete + bucket pre-creado."""
    settings.R2_ENDPOINT_URL = ENDPOINT
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET

    storage_module.reset_default_storage_for_tests()

    with mock_aws():
        # Bucket de juguete dentro del mock
        boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        ).create_bucket(Bucket=BUCKET)
        yield R2Storage()

    storage_module.reset_default_storage_for_tests()


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------
def test_key_for_original_pattern() -> None:
    key = key_for_original("maraton-x", photo_uuid="abc123")
    assert key == "events/maraton-x/originals/abc123.jpg"


def test_key_for_preview_pattern() -> None:
    assert key_for_preview("maraton-x", "abc123") == "events/maraton-x/previews/abc123.webp"


def test_key_for_thumbnail_pattern() -> None:
    assert key_for_thumbnail("maraton-x", "abc123") == "events/maraton-x/thumbnails/abc123.webp"


def test_key_for_zip_generates_uuid() -> None:
    k1 = key_for_zip("maraton-x")
    k2 = key_for_zip("maraton-x")
    assert k1.startswith("events/maraton-x/zips/")
    assert k1.endswith(".zip")
    assert k1 != k2  # distintos UUIDs


# ---------------------------------------------------------------------------
# Storage I/O
# ---------------------------------------------------------------------------
def test_upload_writes_object(r2: R2Storage) -> None:
    buf = BytesIO(b"\xff\xd8\xffhello")  # bytes JPG-ish
    key = r2.upload(buf, "events/x/originals/u1.jpg", content_type="image/jpeg")
    assert key == "events/x/originals/u1.jpg"
    # Verificar leyendo de vuelta
    out = BytesIO()
    r2.download_fileobj(key, out)
    out.seek(0)
    assert out.read() == b"\xff\xd8\xffhello"


def test_get_signed_url_includes_expiry(r2: R2Storage) -> None:
    r2.upload(BytesIO(b"x"), "events/x/originals/u2.jpg")
    url = r2.get_signed_url("events/x/originals/u2.jpg", expires_in=300)
    assert "Expires=" in url or "X-Amz-Expires=" in url
    assert "u2.jpg" in url


def test_delete_removes_object(r2: R2Storage) -> None:
    r2.upload(BytesIO(b"x"), "events/x/originals/u3.jpg")
    r2.delete("events/x/originals/u3.jpg")
    out = BytesIO()
    with pytest.raises(R2UploadError):
        r2.download_fileobj("events/x/originals/u3.jpg", out)


def test_delete_many_batches_correctly(r2: R2Storage) -> None:
    keys = [f"events/x/originals/m{i}.jpg" for i in range(3)]
    for k in keys:
        r2.upload(BytesIO(b"x"), k)
    response = r2.delete_many(keys)
    assert "Deleted" in response
    assert len(response["Deleted"]) == 3


def test_delete_many_empty_list_returns_empty(r2: R2Storage) -> None:
    assert r2.delete_many([]) == {"Deleted": []}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def test_raises_when_not_configured(monkeypatch, settings) -> None:  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = ""
    settings.R2_SECRET_ACCESS_KEY = ""
    settings.R2_BUCKET_NAME = ""

    storage_module.reset_default_storage_for_tests()
    storage = R2Storage()
    with pytest.raises(R2NotConfiguredError):
        storage.upload(BytesIO(b"x"), "k")

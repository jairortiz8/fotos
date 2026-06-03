"""Tests del borrado de datos por selfie (privacidad crítica)."""

from __future__ import annotations

from unittest.mock import patch

import boto3
import numpy as np
import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.core.models import AuditLog
from apps.photos import storage as storage_module
from apps.photos.models import Bib, FaceEmbedding, Photo
from apps.privacy.models import DataDeletionRequest, DeletionStatus
from apps.privacy.tasks import delete_photos_for_request
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory

BUCKET = "test-bucket"


def _emb(dim0: float = 1.0) -> list[float]:
    v = np.zeros(512, dtype=np.float32)
    v[0] = dim0
    v[1] = (1 - dim0**2) ** 0.5 if dim0 < 1 else 0.0
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()


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


def _selfie() -> SimpleUploadedFile:
    return SimpleUploadedFile("me.jpg", b"\xff\xd8\xfffake", content_type="image/jpeg")


# ---------------------------------------------------------------------------
# Task delete_photos_for_request
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_deletion_removes_photos_embeddings_bibs_and_r2(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(slug="del-evt")
    photo = ApprovedPhotoFactory(
        event=event,
        original_key="events/del-evt/originals/p.jpg",
        preview_key="events/del-evt/previews/p.webp",
        thumbnail_key="events/del-evt/thumbnails/p.webp",
    )
    for key in (photo.original_key, photo.preview_key, photo.thumbnail_key):
        r2.put_object(Bucket=BUCKET, Key=key, Body=b"data")
    FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    BibFactory(photo=photo, number="1042")

    deletion = DataDeletionRequest.objects.create(requester_ip_hash="x", matched_photo_count=1)
    delete_photos_for_request.apply(args=[deletion.id, [photo.id]]).get()

    deletion.refresh_from_db()
    assert deletion.status == DeletionStatus.COMPLETED
    assert deletion.deleted_photo_count == 1
    assert deletion.deleted_embedding_count == 1
    assert not Photo.objects.filter(id=photo.id).exists()
    assert not FaceEmbedding.objects.filter(photo_id=photo.id).exists()
    assert not Bib.objects.filter(photo_id=photo.id).exists()
    # R2 borrado
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        r2.head_object(Bucket=BUCKET, Key=photo.original_key)


@pytest.mark.django_db
def test_deletion_creates_audit_log(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory()
    photo = ApprovedPhotoFactory(event=event, original_key="events/x/originals/p.jpg")
    r2.put_object(Bucket=BUCKET, Key=photo.original_key, Body=b"d")
    FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    deletion = DataDeletionRequest.objects.create(requester_ip_hash="x")
    AuditLog.objects.all().delete()
    delete_photos_for_request.apply(args=[deletion.id, [photo.id]]).get()
    assert AuditLog.objects.filter(action="privacy.data_deleted").exists()


@pytest.mark.django_db
def test_deletion_empty_completes(r2) -> None:  # type: ignore[no-untyped-def]
    deletion = DataDeletionRequest.objects.create(requester_ip_hash="x")
    result = delete_photos_for_request.apply(args=[deletion.id, []]).get()
    deletion.refresh_from_db()
    assert deletion.status == DeletionStatus.COMPLETED
    assert result["deleted_photos"] == 0


# ---------------------------------------------------------------------------
# View DeleteMyDataView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_delete_view_requires_confirmation(r2) -> None:  # type: ignore[no-untyped-def]
    client = Client()
    response = client.post(
        reverse("privacy:delete_my_data"),
        {"selfie": _selfie()},  # sin confirmed
        REMOTE_ADDR="4.4.4.4",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "must_confirm"


@pytest.mark.django_db
def test_delete_view_does_not_persist_query_embedding(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory()
    photo = ApprovedPhotoFactory(event=event, original_key="events/x/originals/p.jpg")
    r2.put_object(Bucket=BUCKET, Key=photo.original_key, Body=b"d")
    FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    target = np.array(_emb(), dtype=np.float32)

    client = Client()
    with (
        patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target),
        patch("apps.privacy.tasks.delete_photos_for_request.delay") as mock_task,
    ):
        response = client.post(
            reverse("privacy:delete_my_data"),
            {"selfie": _selfie(), "confirmed": "yes"},
            REMOTE_ADDR="4.4.4.5",
        )
    assert response.status_code == 200
    # La task recibe IDs (no biometría)
    assert mock_task.called
    args = mock_task.call_args.args
    assert isinstance(args[1], list)  # photo_ids
    assert photo.id in args[1]
    # DataDeletionRequest no guarda embedding (el modelo no tiene ese campo)
    dr = DataDeletionRequest.objects.latest("created_at")
    assert not hasattr(dr, "selfie_embedding")


@pytest.mark.django_db
def test_delete_view_no_selfie_returns_400(r2) -> None:  # type: ignore[no-untyped-def]
    client = Client()
    response = client.post(
        reverse("privacy:delete_my_data"),
        {"confirmed": "yes"},
        REMOTE_ADDR="4.4.4.7",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "no_selfie"


@pytest.mark.django_db
def test_delete_view_no_face_renders_page(r2) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.face_recognition import NoFaceDetectedError

    client = Client()
    with patch("apps.ml.face_recognition.embedding_from_bytes", side_effect=NoFaceDetectedError):
        response = client.post(
            reverse("privacy:delete_my_data"),
            {"selfie": _selfie(), "confirmed": "yes"},
            REMOTE_ADDR="4.4.4.8",
        )
    assert response.status_code == 200
    assert b"No detectamos una cara" in response.content


@pytest.mark.django_db
def test_delete_view_multiple_faces_renders_page(r2) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.face_recognition import MultipleFacesDetectedError

    client = Client()
    with patch(
        "apps.ml.face_recognition.embedding_from_bytes",
        side_effect=MultipleFacesDetectedError,
    ):
        response = client.post(
            reverse("privacy:delete_my_data"),
            {"selfie": _selfie(), "confirmed": "yes"},
            REMOTE_ADDR="4.4.4.9",
        )
    assert response.status_code == 200
    assert b"varias caras" in response.content


@pytest.mark.django_db
def test_privacy_policy_page_renders() -> None:
    client = Client()
    response = client.get(reverse("privacy:policy"))
    assert response.status_code == 200
    assert b"reconocimiento facial" in response.content
    assert b"90 d" in response.content  # "90 días"


@pytest.mark.django_db
def test_delete_view_get_renders_form(r2) -> None:  # type: ignore[no-untyped-def]
    client = Client()
    response = client.get(reverse("privacy:delete_my_data"))
    assert response.status_code == 200
    assert b"Borrar mis datos" in response.content


@pytest.mark.django_db
def test_delete_view_rate_limited(r2) -> None:  # type: ignore[no-untyped-def]
    target = np.array(_emb(), dtype=np.float32)
    client = Client()
    last = 200
    with (
        patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target),
        patch("apps.privacy.tasks.delete_photos_for_request.delay"),
    ):
        for _ in range(7):
            r = client.post(
                reverse("privacy:delete_my_data"),
                {"selfie": _selfie(), "confirmed": "yes"},
                REMOTE_ADDR="4.4.4.6",
            )
            last = r.status_code
            if last == 429:
                break
    assert last == 429

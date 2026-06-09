"""Tests de run_face_recognition_on_photo + blur de menores."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from apps.ml.face_recognition import FaceDetection
from apps.ml.synthetic import write_synthetic_jpeg
from apps.photos.models import FaceEmbedding, PhotoStatus
from apps.photos.tasks import run_face_recognition_on_photo
from tests.factories import PhotoFactory


def _det(age: int, emb: list[float] | None = None) -> FaceDetection:
    return FaceDetection(
        embedding=np.array(emb or [0.05] * 512, dtype=np.float32),
        bbox=[100.0, 100.0, 200.0, 200.0],
        det_score=0.9,
        age=age,
        gender="M",
    )


@pytest.fixture
def stub_download(tmp_path: Path):  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    @contextmanager
    def _dl(*_a, **_kw):  # type: ignore[no-untyped-def]
        yield write_synthetic_jpeg("1", target=tmp_path / "from_r2.jpg")

    return _dl


@pytest.mark.django_db
def test_face_task_creates_embeddings(stub_download) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(original_key="events/x/originals/a.jpg")
    with (
        patch("apps.photos.tasks.download_temp_file", stub_download),
        patch("apps.ml.face_recognition.extract_faces", return_value=[_det(30), _det(28)]),
    ):
        result = run_face_recognition_on_photo.apply(args=[photo.id]).get()
    photo.refresh_from_db()
    assert result["faces"] == 2
    assert photo.has_faces_detected is True
    assert FaceEmbedding.objects.filter(photo=photo).count() == 2


@pytest.mark.django_db
def test_face_task_detects_minor_under_16(stub_download) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(original_key="events/x/originals/a.jpg")
    with (
        patch("apps.photos.tasks.download_temp_file", stub_download),
        patch("apps.ml.face_recognition.extract_faces", return_value=[_det(12)]),
        patch("apps.photos.tasks.regenerate_preview_with_minor_blur.delay") as mock_blur,
    ):
        result = run_face_recognition_on_photo.apply(args=[photo.id]).get()
    photo.refresh_from_db()
    assert result["minors"] == 1
    assert photo.has_minors_detected is True
    assert photo.needs_minor_review is True
    assert FaceEmbedding.objects.get(photo=photo).is_minor is True
    assert mock_blur.called  # se dispara el blur


@pytest.mark.django_db
def test_face_task_marks_review_for_doubtful_age(stub_download) -> None:  # type: ignore[no-untyped-def]
    """Cara estimada en 19 (<22 pero >=16): no es menor, pero marca review."""
    photo = PhotoFactory(original_key="events/x/originals/a.jpg")
    with (
        patch("apps.photos.tasks.download_temp_file", stub_download),
        patch("apps.ml.face_recognition.extract_faces", return_value=[_det(19)]),
        patch("apps.photos.tasks.regenerate_preview_with_minor_blur.delay") as mock_blur,
    ):
        run_face_recognition_on_photo.apply(args=[photo.id]).get()
    photo.refresh_from_db()
    assert photo.has_minors_detected is False
    assert photo.needs_minor_review is True
    assert FaceEmbedding.objects.get(photo=photo).is_minor is False
    assert not mock_blur.called  # NO se blurea (no es menor confirmado)


@pytest.mark.django_db
def test_face_task_no_faces(stub_download) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(original_key="events/x/originals/a.jpg")
    with (
        patch("apps.photos.tasks.download_temp_file", stub_download),
        patch("apps.ml.face_recognition.extract_faces", return_value=[]),
    ):
        result = run_face_recognition_on_photo.apply(args=[photo.id]).get()
    assert result["faces"] == 0
    assert not FaceEmbedding.objects.filter(photo=photo).exists()


@pytest.mark.django_db
def test_face_task_skips_deleted(stub_download) -> None:  # type: ignore[no-untyped-def]
    photo = PhotoFactory(status=PhotoStatus.DELETED)
    with patch("apps.photos.tasks.download_temp_file") as mock_dl:
        result = run_face_recognition_on_photo.apply(args=[photo.id]).get()
    assert mock_dl.called is False
    assert result.get("skipped") == "status"


@pytest.mark.django_db
def test_face_task_skips_already_indexed(stub_download) -> None:  # type: ignore[no-untyped-def]
    """Idempotencia: si la foto ya tiene caras detectadas, NO re-procesa (evita
    duplicar embeddings y no carga el modelo). Ni siquiera descarga el original."""
    photo = PhotoFactory(has_faces_detected=True)
    with patch("apps.photos.tasks.download_temp_file") as mock_dl:
        result = run_face_recognition_on_photo.apply(args=[photo.id]).get()
    assert mock_dl.called is False
    assert result.get("skipped") == "already_indexed"


# ---------------------------------------------------------------------------
# Blur de menores (imaging)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_blur_applied_and_original_not_modified(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import boto3
    from django.test import override_settings
    from moto import mock_aws

    from apps.photos import storage as storage_module
    from apps.photos.imaging import blur_minor_faces_and_regenerate
    from tests.factories import EventFactory

    with override_settings(
        R2_ENDPOINT_URL="",
        R2_ACCESS_KEY_ID="AKIA-TEST",
        R2_SECRET_ACCESS_KEY="SECRET-TEST",
        R2_BUCKET_NAME="test-bucket",
    ):
        storage_module.reset_default_storage_for_tests()
        with mock_aws():
            boto3.client(
                "s3",
                aws_access_key_id="AKIA-TEST",
                aws_secret_access_key="SECRET-TEST",
                region_name="us-east-1",
            ).create_bucket(Bucket="test-bucket")

            event = EventFactory(slug="blur-evt")
            photo = PhotoFactory(event=event, original_key="events/blur-evt/originals/m.jpg")
            source = write_synthetic_jpeg("1", target=tmp_path / "orig.jpg")
            original_bytes = source.read_bytes()

            from types import SimpleNamespace

            minor = SimpleNamespace(bbox={"x1": 100, "y1": 100, "x2": 400, "y2": 400})
            preview_key, thumb_key = blur_minor_faces_and_regenerate(photo, source, [minor])

            assert preview_key.endswith(".webp")
            assert thumb_key.endswith(".webp")
            # El archivo original en disco NO se modificó.
            assert source.read_bytes() == original_bytes
        storage_module.reset_default_storage_for_tests()


# ---------------------------------------------------------------------------
# reindex_missing_faces (auto-recuperación)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_reindex_missing_faces_reenqueues_unindexed(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings.FACE_PROCESSING_ENABLED = True
    from apps.photos.tasks import reindex_missing_faces

    missing = PhotoFactory(status=PhotoStatus.APPROVED, has_faces_detected=False)
    indexed = PhotoFactory(status=PhotoStatus.APPROVED, has_faces_detected=True)
    enqueued: list[int] = []
    monkeypatch.setattr(
        "apps.photos.tasks.run_face_recognition_on_photo.delay",
        lambda pid: enqueued.append(pid),
    )
    result = reindex_missing_faces.apply(kwargs={"days": 2, "limit": 100}).get()
    assert result["reenqueued"] == 1
    assert missing.id in enqueued
    assert indexed.id not in enqueued  # ya indexada → no se re-encola


@pytest.mark.django_db
def test_reindex_missing_faces_noop_when_disabled(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings.FACE_PROCESSING_ENABLED = False
    from apps.photos.tasks import reindex_missing_faces

    PhotoFactory(status=PhotoStatus.APPROVED, has_faces_detected=False)
    called: list[int] = []
    monkeypatch.setattr(
        "apps.photos.tasks.run_face_recognition_on_photo.delay", lambda pid: called.append(pid)
    )
    result = reindex_missing_faces.apply(kwargs={}).get()
    assert result["reenqueued"] == 0
    assert called == []

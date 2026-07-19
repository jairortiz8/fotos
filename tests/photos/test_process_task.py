"""Tests del pipeline Celery (process_photo + run_ocr_on_photo) con mocks."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.ml.ocr import BibDetection
from apps.ml.synthetic import write_synthetic_jpeg
from apps.photos.models import Bib, PhotoStatus
from apps.photos.tasks import process_photo, run_ocr_on_photo
from tests.factories import EventFactory, PhotoFactory


@contextmanager
def _stub_download(tmp_path: Path, bib_number: str = "1042") -> Iterator[Path]:
    """Reemplaza `download_temp_file` con un archivo sintético local."""
    fake = write_synthetic_jpeg(bib_number, target=tmp_path / "from_r2.jpg")
    yield fake


# ---------------------------------------------------------------------------
# process_photo
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_process_photo_runs_full_pipeline(tmp_path: Path) -> None:
    event = EventFactory(slug="test-process")
    photo = PhotoFactory(
        event=event,
        original_key="events/test-process/originals/abc123.jpg",
        status=PhotoStatus.UPLOADING,
        preview_key="",
        thumbnail_key="",
    )

    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.photos.tasks.generate_preview", return_value="events/x/previews/abc.webp"),
        patch("apps.photos.tasks.generate_thumbnail", return_value="events/x/thumbs/abc.webp"),
        patch("apps.photos.tasks.run_ocr_on_photo.delay") as mock_ocr,
    ):
        result = process_photo.apply(args=[photo.id]).get()

    photo.refresh_from_db()
    assert photo.status == PhotoStatus.PENDING_REVIEW
    assert photo.preview_key == "events/x/previews/abc.webp"
    assert photo.thumbnail_key == "events/x/thumbs/abc.webp"
    assert photo.width > 0
    assert photo.height > 0
    assert mock_ocr.called
    assert result["status"] == PhotoStatus.PENDING_REVIEW


@pytest.mark.django_db
def test_process_photo_skips_deleted(tmp_path: Path) -> None:
    photo = PhotoFactory(status=PhotoStatus.DELETED)
    with patch("apps.photos.tasks.download_temp_file") as mock_dl:
        result = process_photo.apply(args=[photo.id]).get()
    assert mock_dl.called is False
    assert result == {"photo_id": photo.id, "skipped": "deleted"}


# ---------------------------------------------------------------------------
# run_ocr_on_photo
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_run_ocr_creates_bibs(tmp_path: Path) -> None:
    photo = PhotoFactory(
        original_key="events/x/originals/abc.jpg",
        has_bibs_detected=False,
    )

    fake_detections = [
        BibDetection(
            number="1042",
            confidence=0.95,
            bbox={"x": 0, "y": 0, "w": 0.1, "h": 0.05},
            engine="paddle",
        ),
        BibDetection(
            number="A77",
            confidence=0.81,
            bbox={"x": 0, "y": 0, "w": 0.1, "h": 0.05},
            engine="paddle",
        ),
    ]

    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.ocr.detect_bibs", return_value=fake_detections),
    ):
        result = run_ocr_on_photo.apply(args=[photo.id]).get()

    photo.refresh_from_db()
    assert photo.has_bibs_detected is True
    assert Bib.objects.filter(photo=photo, number="1042").exists()
    assert Bib.objects.filter(photo=photo, number="A77").exists()
    assert result["created"] == 2


@pytest.mark.django_db
def test_run_ocr_idempotent(tmp_path: Path) -> None:
    """Correr OCR dos veces no duplica bibs (unique(photo, number, source))."""
    photo = PhotoFactory(original_key="events/x/originals/abc.jpg")
    det = BibDetection(number="1042", confidence=0.95, bbox={}, engine="paddle")

    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.ocr.detect_bibs", return_value=[det]),
    ):
        run_ocr_on_photo.apply(args=[photo.id]).get()
        result_second = run_ocr_on_photo.apply(args=[photo.id]).get()

    assert Bib.objects.filter(photo=photo, number="1042").count() == 1
    assert result_second["created"] == 0


@pytest.mark.django_db
def test_run_ocr_with_no_detections(tmp_path: Path) -> None:
    photo = PhotoFactory(original_key="events/x/originals/abc.jpg")
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.ocr.detect_bibs", return_value=[]),
    ):
        result = run_ocr_on_photo.apply(args=[photo.id]).get()
    assert result["detected"] == 0
    assert result["created"] == 0
    assert not Bib.objects.filter(photo=photo).exists()


@pytest.mark.django_db
def test_process_photo_enqueues_ocr_exhaustive_per_setting(tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """OCR_EXHAUSTIVE_ON_UPLOAD gobierna el modo del OCR post-subida."""
    for flag in (True, False):
        settings.OCR_EXHAUSTIVE_ON_UPLOAD = flag
        photo = PhotoFactory(
            original_key=f"events/x/originals/exh-{flag}.jpg", status=PhotoStatus.UPLOADING
        )
        with (
            patch(
                "apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)
            ),
            patch("apps.photos.tasks.generate_preview", return_value="p.webp"),
            patch("apps.photos.tasks.generate_thumbnail", return_value="t.webp"),
            patch("apps.photos.tasks.run_ocr_on_photo.delay") as mock_ocr,
        ):
            process_photo.apply(args=[photo.id]).get()
        mock_ocr.assert_called_once_with(photo.id, exhaustive=flag)


@pytest.mark.django_db
def test_run_ocr_gemini_backend_creates_bibs_with_gemini_source(tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """Con OCR_BACKEND=gemini, los dorsales salen de la API y quedan con
    source=ocr_gemini (sin tocar los engines locales)."""
    from apps.photos.models import BibSource

    settings.OCR_BACKEND = "gemini"
    photo = PhotoFactory(original_key="events/x/originals/gm.jpg")
    det = BibDetection(number="415", confidence=0.9, bbox={}, engine="gemini")
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", return_value=[det]) as mock_gemini,
        patch("apps.ml.ocr.detect_bibs") as mock_local,
    ):
        result = run_ocr_on_photo.apply(args=[photo.id]).get()
    assert mock_gemini.called
    assert not mock_local.called  # el local NI se toca si la API responde
    assert result["created"] == 1
    bib = Bib.objects.get(photo=photo)
    assert bib.number == "415"
    assert bib.source == BibSource.OCR_GEMINI


@pytest.mark.django_db
def test_run_ocr_gemini_falls_back_to_local_on_api_error(tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """Si la API falla (red/cuota), cae al OCR local — la foto nunca queda sin
    intento de OCR."""
    from apps.ml.gemini_ocr import GeminiOCRError

    settings.OCR_BACKEND = "gemini"
    photo = PhotoFactory(original_key="events/x/originals/gm2.jpg")
    det = BibDetection(number="77", confidence=0.6, bbox={}, engine="paddle")
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("cuota")),
        patch("apps.ml.ocr.detect_bibs", return_value=[det]) as mock_local,
    ):
        result = run_ocr_on_photo.apply(args=[photo.id]).get()
    assert mock_local.called
    assert result["created"] == 1
    assert Bib.objects.get(photo=photo).source == "ocr_paddle"


@pytest.mark.django_db
def test_run_ocr_local_backend_ignores_gemini(tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    settings.OCR_BACKEND = "local"
    photo = PhotoFactory(original_key="events/x/originals/lc.jpg")
    det = BibDetection(number="88", confidence=0.7, bbox={}, engine="easy")
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.ocr.detect_bibs", return_value=[det]) as mock_local,
    ):
        run_ocr_on_photo.apply(args=[photo.id]).get()
    assert mock_local.called
    assert Bib.objects.get(photo=photo).source == "ocr_easy"


@pytest.mark.django_db
def test_run_ocr_exhaustive_passes_flag_and_clears_cache(tmp_path: Path) -> None:
    """El modo exhaustivo pasa exhaustive=True a detect_bibs y, al terminar,
    limpia el flag de cache `ocr_rerun:<id>` (corta el "re-detectando…")."""
    from django.core.cache import cache

    photo = PhotoFactory(original_key="events/x/originals/abc.jpg")
    cache.set(f"ocr_rerun:{photo.id}", "1", 180)
    captured: dict[str, object] = {}

    def fake_detect(_path: Path, *, exhaustive: bool = False) -> list[BibDetection]:
        captured["exhaustive"] = exhaustive
        return []

    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.ocr.detect_bibs", side_effect=fake_detect),
    ):
        run_ocr_on_photo.apply(args=[photo.id], kwargs={"exhaustive": True}).get()

    assert captured["exhaustive"] is True
    assert cache.get(f"ocr_rerun:{photo.id}") is None  # flag limpiado


# ---------------------------------------------------------------------------
# regenerate_thumbnail
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_regenerate_thumbnail_updates_key_without_reapproving(tmp_path: Path) -> None:
    """Regenera el thumbnail y actualiza su key SIN cambiar el status: sirve
    para subir la nitidez de un evento ya aprobado sin re-aprobarlo."""
    from apps.photos.tasks import regenerate_thumbnail

    event = EventFactory(slug="test-regen")
    photo = PhotoFactory(
        event=event,
        original_key="events/test-regen/originals/abc123.jpg",
        status=PhotoStatus.APPROVED,
        thumbnail_key="events/test-regen/thumbnails/abc123.webp",
        preview_key="events/test-regen/previews/abc123.webp",
    )
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch(
            "apps.photos.tasks.generate_thumbnail", return_value="events/x/thumbs/new.webp"
        ) as m_t,
        patch("apps.photos.tasks.generate_preview") as m_p,
    ):
        regenerate_thumbnail.apply(args=[photo.id]).get()

    photo.refresh_from_db()
    assert photo.thumbnail_key == "events/x/thumbs/new.webp"
    assert photo.status == PhotoStatus.APPROVED  # NO se re-aprueba
    assert m_t.called
    assert not m_p.called  # sin include_preview no toca el preview


@pytest.mark.django_db
def test_regenerate_thumbnail_with_preview_opt_in(tmp_path: Path) -> None:
    from apps.photos.tasks import regenerate_thumbnail

    photo = PhotoFactory(
        event=EventFactory(slug="test-regen-prev"),
        original_key="events/test-regen-prev/originals/abc.jpg",
        status=PhotoStatus.APPROVED,
    )
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.photos.tasks.generate_thumbnail", return_value="t.webp"),
        patch("apps.photos.tasks.generate_preview", return_value="p.webp") as m_p,
    ):
        regenerate_thumbnail.apply(args=[photo.id], kwargs={"include_preview": True}).get()

    photo.refresh_from_db()
    assert photo.preview_key == "p.webp"
    assert m_p.called

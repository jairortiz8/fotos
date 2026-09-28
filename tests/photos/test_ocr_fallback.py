"""Fallback de OCR local cuando falla Gemini (flag OCR_LOCAL_FALLBACK).

Incidente UTCOM 2026-09-27: el fallback cargaba Paddle+EasyOCR en cada proceso
del worker y agotó sus hilos. En prod se apaga; estos tests fijan el contrato.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from celery.exceptions import Retry

from apps.ml.gemini_ocr import GeminiOCRError
from apps.ml.ocr import BibDetection
from apps.photos.models import Bib, PhotoStatus
from apps.photos.tasks import _detect_bibs, run_ocr_on_photo
from tests.factories import PhotoFactory


@pytest.fixture
def gemini(settings):  # type: ignore[no-untyped-def]
    settings.OCR_BACKEND = "gemini"
    settings.GEMINI_API_KEY = "test-key"
    return settings


def test_fallback_off_raises_and_skips_local(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    gemini.OCR_LOCAL_FALLBACK = False
    with (
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("timeout")),
        patch("apps.ml.ocr.detect_bibs") as local,
        pytest.raises(GeminiOCRError),
    ):
        _detect_bibs(tmp_path / "x.jpg", exhaustive=False, photo_id=1)
    local.assert_not_called()


def test_fallback_on_uses_local(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    gemini.OCR_LOCAL_FALLBACK = True
    local_result = [BibDetection(number="415", confidence=0.8, bbox={}, engine="easy")]
    with (
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("timeout")),
        patch("apps.ml.ocr.detect_bibs", return_value=local_result) as local,
    ):
        result = _detect_bibs(tmp_path / "x.jpg", exhaustive=False, photo_id=1)
    local.assert_called_once()
    assert result == local_result


def test_gemini_timeout_comes_from_settings(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    gemini.GEMINI_OCR_TIMEOUT = 30
    with patch("apps.ml.gemini_ocr.detect_bibs_gemini", return_value=[]) as call:
        _detect_bibs(tmp_path / "x.jpg", exhaustive=False, photo_id=1)
    assert call.call_args.kwargs["timeout"] == 30


@contextmanager
def _stub_download(tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "src.jpg"
    target.write_bytes(b"x")
    yield target


@pytest.mark.django_db
def test_run_ocr_without_fallback_leaves_photo_intact(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Gemini cae y no hay fallback: la task se reintenta, no crea dorsales y
    no toca el estado ni el preview de la foto (sigue aprobada y visible)."""
    gemini.OCR_LOCAL_FALLBACK = False
    photo = PhotoFactory(status=PhotoStatus.APPROVED, preview_key="p.webp")
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("timeout")),
        patch("apps.ml.ocr.detect_bibs") as local,
        pytest.raises((GeminiOCRError, Retry)),
    ):
        run_ocr_on_photo.apply(args=[photo.id], throw=True)
    local.assert_not_called()
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.APPROVED
    assert photo.preview_key == "p.webp"
    assert not Bib.objects.filter(photo=photo).exists()

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


def test_ocr_task_retries_for_about_an_hour_and_a_half() -> None:
    """Sin fallback, el reintento es la única recuperación: tiene que cubrir
    caídas largas de Gemini (antes: 2 reintentos fijos de 120 s ≈ 5 min)."""
    from celery.utils.time import get_exponential_backoff_interval

    assert run_ocr_on_photo.max_retries == 8
    assert run_ocr_on_photo.retry_jitter is False  # esperas deterministas
    waits = [
        get_exponential_backoff_interval(
            factor=run_ocr_on_photo.retry_backoff,
            retries=n,
            maximum=run_ocr_on_photo.retry_backoff_max,
            full_jitter=run_ocr_on_photo.retry_jitter,
        )
        for n in range(run_ocr_on_photo.max_retries)
    ]
    assert waits == [60, 120, 240, 480, 960, 1200, 1200, 1200]
    # Holgura contra el visibility_timeout de Redis (1 h).
    assert max(waits) <= 1200


def test_ocr_retries_stay_in_ocr_queue(settings) -> None:  # type: ignore[no-untyped-def]
    """Celery re-encola un retry en la cola de ORIGEN (no usa las rutas): el
    queue explícito hace que siempre vuelvan a la cola del OCR."""
    # (Celery además escribe "countdown" en este mismo dict en cada retry.)
    assert run_ocr_on_photo.retry_kwargs["queue"] == settings.OCR_QUEUE


def test_ocr_routes_to_configured_queue(settings) -> None:  # type: ignore[no-untyped-def]
    assert settings.CELERY_TASK_ROUTES["photos.run_ocr_on_photo"]["queue"] == settings.OCR_QUEUE
    assert settings.CELERY_TASK_ROUTES["photos.process_photo"]["queue"] == "fast"


@pytest.mark.django_db
def test_redetect_flag_kept_while_retries_remain(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """'Re-detectar' del dashboard: si falla pero quedan reintentos, el
    indicador sigue prendido (antes se apagaba en el primer fallo)."""
    from django.core.cache import cache

    gemini.OCR_LOCAL_FALLBACK = False
    photo = PhotoFactory(status=PhotoStatus.APPROVED, preview_key="p.webp")
    cache.set(f"ocr_rerun:{photo.id}", True, 300)
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("timeout")),
        patch.object(run_ocr_on_photo, "retry", side_effect=Retry()),
        pytest.raises(Retry),
    ):
        run_ocr_on_photo.apply(args=[photo.id], kwargs={"exhaustive": True}, retries=0, throw=True)
    assert cache.get(f"ocr_rerun:{photo.id}") is True


@pytest.mark.django_db
def test_redetect_flag_cleared_on_last_attempt(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    gemini.OCR_LOCAL_FALLBACK = False
    photo = PhotoFactory(status=PhotoStatus.APPROVED, preview_key="p.webp")
    cache.set(f"ocr_rerun:{photo.id}", True, 300)
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", side_effect=GeminiOCRError("timeout")),
        pytest.raises(GeminiOCRError),
    ):
        run_ocr_on_photo.apply(
            args=[photo.id],
            kwargs={"exhaustive": True},
            retries=run_ocr_on_photo.max_retries,
            throw=True,
        )
    assert cache.get(f"ocr_rerun:{photo.id}") is None


@pytest.mark.django_db
def test_redetect_flag_cleared_on_success(gemini, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    photo = PhotoFactory(status=PhotoStatus.APPROVED, preview_key="p.webp")
    cache.set(f"ocr_rerun:{photo.id}", True, 300)
    dets = [BibDetection(number="415", confidence=0.9, bbox={}, engine="gemini")]
    with (
        patch("apps.photos.tasks.download_temp_file", lambda *a, **kw: _stub_download(tmp_path)),
        patch("apps.ml.gemini_ocr.detect_bibs_gemini", return_value=dets),
    ):
        run_ocr_on_photo.apply(args=[photo.id], kwargs={"exhaustive": True}, throw=True)
    assert cache.get(f"ocr_rerun:{photo.id}") is None
    assert Bib.objects.filter(photo=photo, number="415").exists()

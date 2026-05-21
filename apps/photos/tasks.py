"""Celery tasks de procesamiento de fotos.

`process_photo` corre el pipeline completo: descarga el original, extrae EXIF,
genera preview con watermark y thumbnail, los sube a R2, dispara OCR.

`run_ocr_on_photo` es la task de OCR (encadenada desde `process_photo`).
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from celery import shared_task
from django.db import transaction

from apps.photos.imaging import (
    extract_exif_and_dimensions,
    generate_preview,
    generate_thumbnail,
)
from apps.photos.models import Bib, Photo, PhotoStatus
from apps.photos.storage import default_storage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def download_temp_file(key: str, *, suffix: str = ".jpg") -> Iterator[Path]:
    """Descarga un objeto de R2 a un archivo temporal y lo limpia al salir."""
    storage = default_storage()
    fd, raw_path = tempfile.mkstemp(suffix=suffix, prefix="rf_")
    path = Path(raw_path)
    try:
        with path.open("wb") as fh:
            storage.download_fileobj(key, fh)
        yield path
    finally:
        try:
            import os

            os.close(fd)
        except OSError:
            pass
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("No pude borrar tempfile %s", path)


# ---------------------------------------------------------------------------
# process_photo
# ---------------------------------------------------------------------------
@shared_task(
    bind=True,
    name="photos.process_photo",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def process_photo(self, photo_id: int) -> dict[str, str | int]:
    """Pipeline: EXIF + preview + thumb + dispara OCR.

    Devuelve un dict con resumen (útil para logs / chain).
    """
    photo = Photo.objects.select_related("event").get(id=photo_id)
    if photo.status == PhotoStatus.DELETED:
        logger.info("Photo %s borrada antes de procesar; skip", photo_id)
        return {"photo_id": photo_id, "skipped": "deleted"}

    photo.status = PhotoStatus.PROCESSING
    photo.save(update_fields=["status", "updated_at"])

    try:
        with download_temp_file(photo.original_key) as source:
            extract_exif_and_dimensions(photo, source)
            photo.preview_key = generate_preview(photo, source)
            photo.thumbnail_key = generate_thumbnail(photo, source)
    except Exception:
        logger.exception("Falló process_photo(%s)", photo_id)
        photo.refresh_from_db()
        photo.status = PhotoStatus.PENDING_REVIEW  # dejamos que el admin decida
        photo.save(update_fields=["status", "updated_at"])
        raise  # autoretry se activa

    photo.status = PhotoStatus.PENDING_REVIEW
    photo.save(
        update_fields=[
            "width",
            "height",
            "capture_time",
            "camera_make",
            "camera_model",
            "lens_model",
            "iso",
            "focal_length",
            "aperture",
            "shutter_speed",
            "exif_raw",
            "preview_key",
            "thumbnail_key",
            "status",
            "updated_at",
        ]
    )

    # OCR como task separada — independiente del resto.
    run_ocr_on_photo.delay(photo.id)

    return {
        "photo_id": photo.id,
        "status": photo.status,
        "preview_key": photo.preview_key,
        "thumbnail_key": photo.thumbnail_key,
    }


# ---------------------------------------------------------------------------
# run_ocr_on_photo
# ---------------------------------------------------------------------------
@shared_task(
    name="photos.run_ocr_on_photo",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    autoretry_for=(Exception,),
)
def run_ocr_on_photo(self, photo_id: int) -> dict[str, int | list[str]]:
    """OCR sobre el original, crea registros `Bib`, marca `has_bibs_detected`."""
    from apps.ml.ocr import detect_bibs  # import local (libs pesadas)

    photo = Photo.objects.get(id=photo_id)
    if photo.status == PhotoStatus.DELETED:
        return {"photo_id": photo_id, "skipped": ["deleted"]}

    bib_sources_created: list[str] = []
    with download_temp_file(photo.original_key) as source:
        detections = detect_bibs(source)

    if not detections:
        return {"photo_id": photo.id, "detected": 0, "created": 0}

    with transaction.atomic():
        for det in detections:
            source_value = "ocr_paddle" if det.engine == "paddle" else "ocr_easy"
            _bib, created = Bib.objects.get_or_create(
                photo=photo,
                number=det.number,
                source=source_value,
                defaults={
                    "confidence": det.confidence,
                    "bbox": det.bbox,
                },
            )
            if created:
                bib_sources_created.append(f"{det.number}/{source_value}")

        if not photo.has_bibs_detected:
            photo.has_bibs_detected = True
            photo.save(update_fields=["has_bibs_detected", "updated_at"])

    return {
        "photo_id": photo.id,
        "detected": len(detections),
        "created": len(bib_sources_created),
        "bibs": bib_sources_created,
    }

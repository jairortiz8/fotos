"""Celery tasks de descargas: generar ZIP + limpiar expirados."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import zipfile
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.downloads.models import ZipDownload, ZipStatus
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import default_storage, key_for_zip

logger = logging.getLogger(__name__)

ZIP_TTL_HOURS = 1


@shared_task(name="downloads.generate_zip", bind=True, max_retries=2, default_retry_delay=30)
def generate_zip(self, download_id: int) -> dict[str, object]:
    """Arma un ZIP con los ORIGINALES (sin watermark) y lo sube a R2."""
    download = ZipDownload.objects.get(id=download_id)
    download.status = ZipStatus.PROCESSING
    download.save(update_fields=["status", "updated_at"])

    photos = list(
        Photo.objects.filter(id__in=download.photo_ids, status=PhotoStatus.APPROVED).select_related(
            "event"
        )
    )
    if not photos:
        download.status = ZipStatus.FAILED
        download.error_message = "No hay fotos aprobadas en la selección."
        download.save(update_fields=["status", "error_message", "updated_at"])
        return {"download_id": download_id, "status": "failed", "reason": "no_photos"}

    storage = default_storage()
    event_slug = photos[0].event.slug
    total_bytes = 0

    fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="rf_zip_")
    os.close(fd)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            used_names: set[str] = set()
            for photo in photos:
                if not photo.original_key:
                    continue
                arcname = _safe_arcname(photo.original_filename, photo.id, used_names)
                # Descargamos el original de R2 a un tempfile y lo metemos al ZIP.
                with tempfile.NamedTemporaryFile(delete=True) as tmp:
                    storage.download_fileobj(photo.original_key, tmp)
                    tmp.flush()
                    zf.write(tmp.name, arcname=arcname)
                total_bytes += photo.file_size or 0

        # Subir el ZIP a R2.
        zip_key = key_for_zip(event_slug, zip_uuid=str(download.id))
        with open(zip_path, "rb") as zfh:
            storage.upload(zfh, zip_key, content_type="application/zip")

        signed_url = storage.get_signed_url(zip_key, expires_in=ZIP_TTL_HOURS * 3600)

        download.zip_key = zip_key
        download.download_url = signed_url
        download.total_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        download.status = ZipStatus.READY
        download.expires_at = timezone.now() + timedelta(hours=ZIP_TTL_HOURS)
        download.save(
            update_fields=[
                "zip_key",
                "download_url",
                "total_size_mb",
                "status",
                "expires_at",
                "updated_at",
            ]
        )
    except Exception as exc:
        logger.exception("Falló generate_zip(%s)", download_id)
        download.status = ZipStatus.FAILED
        download.error_message = str(exc)[:500]
        download.save(update_fields=["status", "error_message", "updated_at"])
        raise self.retry(exc=exc) from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(zip_path)

    return {
        "download_id": download.id,
        "status": download.status,
        "photos": len(photos),
        "size_mb": download.total_size_mb,
    }


@shared_task(name="downloads.cleanup_expired_zips")
def cleanup_expired_zips() -> dict[str, int]:
    """Borra de R2 los ZIPs que ya expiraron. Corre cada hora (beat)."""
    expired = list(
        ZipDownload.objects.filter(
            status=ZipStatus.READY,
            expires_at__lt=timezone.now(),
        )
    )
    if not expired:
        return {"expired": 0, "deleted_from_r2": 0}

    keys = [d.zip_key for d in expired if d.zip_key]
    deleted = 0
    if keys:
        try:
            default_storage().delete_many(keys)
            deleted = len(keys)
        except Exception:
            logger.exception("cleanup_expired_zips: error borrando %d keys", len(keys))

    ZipDownload.objects.filter(id__in=[d.id for d in expired]).update(
        status=ZipStatus.EXPIRED,
        zip_key="",
        download_url="",
    )
    return {"expired": len(expired), "deleted_from_r2": deleted}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_arcname(filename: str, photo_id: int, used: set[str]) -> str:
    """Nombre único dentro del ZIP, preservando el original cuando se puede."""
    base = filename or f"foto_{photo_id}.jpg"
    if base not in used:
        used.add(base)
        return base
    # Colisión: prefijo con el ID.
    stem, dot, ext = base.rpartition(".")
    candidate = f"{stem}_{photo_id}.{ext}" if dot else f"{base}_{photo_id}"
    used.add(candidate)
    return candidate

"""Celery tasks de privacidad: borrado de datos + retención de embeddings.

Ninguna de estas tasks recibe biometría: `delete_photos_for_request` recibe
sólo `photo_ids` (no embeddings). El embedding del solicitante se procesó y
descartó en la vista (síncrono).
"""

from __future__ import annotations

import datetime as dt
import logging

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AuditLog
from apps.photos.models import Bib, FaceEmbedding, Photo
from apps.photos.storage import R2NotConfiguredError, default_storage
from apps.privacy.models import DataDeletionRequest, DeletionStatus

logger = logging.getLogger(__name__)

EMBEDDING_RETENTION_DAYS = 90


@shared_task(name="privacy.delete_photos_for_request", bind=True, max_retries=2)
def delete_photos_for_request(self, deletion_id: int, photo_ids: list[int]) -> dict[str, int]:
    """Borra las fotos matcheadas (embeddings + bibs + R2 + Photo)."""
    deletion = DataDeletionRequest.objects.get(id=deletion_id)

    if not photo_ids:
        deletion.status = DeletionStatus.COMPLETED
        deletion.completed_at = timezone.now()
        deletion.save(update_fields=["status", "completed_at", "updated_at"])
        return {"deleted_photos": 0, "deleted_embeddings": 0}

    try:
        # 1. Contar embeddings antes de borrar (para el registro).
        emb_count = FaceEmbedding.objects.filter(photo_id__in=photo_ids).count()

        # 2. Recolectar keys de R2 a borrar.
        keys: list[str] = []
        for photo in Photo.objects.filter(id__in=photo_ids):
            keys.extend(
                k for k in (photo.original_key, photo.preview_key, photo.thumbnail_key) if k
            )

        # 3. Borrar de R2 (best-effort: si R2 no está, seguimos con la DB).
        if keys:
            try:
                default_storage().delete_many(keys)
            except R2NotConfiguredError:
                logger.warning("delete_photos: R2 no configurado; borro solo DB")

        # 4. Borrar de la DB (embeddings y bibs caen por CASCADE al borrar Photo,
        #    pero los contamos arriba). Borramos Photo explícitamente.
        FaceEmbedding.objects.filter(photo_id__in=photo_ids).delete()
        Bib.objects.filter(photo_id__in=photo_ids).delete()
        Photo.objects.filter(id__in=photo_ids).delete()

        deletion.deleted_photo_count = len(photo_ids)
        deletion.deleted_embedding_count = emb_count
        deletion.status = DeletionStatus.COMPLETED
        deletion.completed_at = timezone.now()
        deletion.save(
            update_fields=[
                "deleted_photo_count",
                "deleted_embedding_count",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        AuditLog.log(
            "privacy.data_deleted",
            metadata={
                "deletion_request_id": deletion.id,
                "photo_count": deletion.deleted_photo_count,
                "embedding_count": deletion.deleted_embedding_count,
            },
        )
    except Exception as exc:
        logger.exception("delete_photos_for_request(%s) falló", deletion_id)
        deletion.status = DeletionStatus.FAILED
        deletion.error_message = str(exc)[:500]
        deletion.save(update_fields=["status", "error_message", "updated_at"])
        raise self.retry(exc=exc) from exc

    return {
        "deleted_photos": deletion.deleted_photo_count,
        "deleted_embeddings": deletion.deleted_embedding_count,
    }


@shared_task(name="privacy.cleanup_old_embeddings")
def cleanup_old_embeddings() -> dict[str, int]:
    """Borra embeddings inactivos > 90 días. Corre diariamente (beat).

    Un embedding "expira" si:
    - nunca matcheó (`last_matched_at` NULL) y se creó hace > 90 días, o
    - su último match fue hace > 90 días.
    """
    cutoff = timezone.now() - dt.timedelta(days=EMBEDDING_RETENTION_DAYS)
    expired = FaceEmbedding.objects.filter(
        Q(last_matched_at__isnull=True, created_at__lt=cutoff) | Q(last_matched_at__lt=cutoff)
    )
    count = expired.count()
    expired.delete()

    AuditLog.log("privacy.embeddings_cleanup", metadata={"deleted_count": count})
    return {"deleted_count": count}

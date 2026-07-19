"""Celery tasks de privacidad: borrado de datos + retención de embeddings.

Ninguna de estas tasks recibe biometría: `delete_photos_for_request` recibe
sólo `photo_ids` (no embeddings). El embedding del solicitante se procesó y
descartó en la vista (síncrono).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AuditLog
from apps.events.models import Event, EventStatus
from apps.photographers.models import PhotographerLink
from apps.photos.models import Bib, FaceEmbedding, Photo, PhotoStatus
from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage
from apps.privacy.models import DataDeletionRequest, DeletionStatus

logger = logging.getLogger(__name__)

EMBEDDING_RETENTION_DAYS = 90
ARCHIVED_GRACE_DAYS = 30  # tiempo en `archived` antes de pasar a pending_deletion
AUDIT_LOG_RETENTION_DAYS = 2 * 365
STUCK_PHOTO_HOURS = 1
ORPHAN_ALERT_THRESHOLD = 100  # si hay más huérfanos que esto, NO borramos: alertamos
R2_DELETE_BATCH = 1000  # límite de delete_objects de R2/S3


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


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

        # 2. Recolectar keys de R2 a borrar (incl. branded_key: la copia full-res
        #    con logos del usuario NO debe sobrevivir a un pedido de borrado).
        keys: list[str] = []
        for photo in Photo.objects.filter(id__in=photo_ids):
            keys.extend(
                k
                for k in (
                    photo.original_key,
                    photo.preview_key,
                    photo.thumbnail_key,
                    photo.branded_key,
                )
                if k
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


# ---------------------------------------------------------------------------
# Retención escalonada de EVENTOS (Fase 6)
# ---------------------------------------------------------------------------
@shared_task(name="privacy.enforce_event_retention_policy")
def enforce_event_retention_policy() -> dict[str, int]:
    """Avanza el estado de los eventos según sus fechas de retención (beat 2 AM).

    live → public_closed → searchable_only → archived → pending_deletion.
    `permanent_archive=True` ignora todas las transiciones. Idempotente: cada
    transición filtra por el estado actual + la fecha, así re-correr no hace nada.
    """
    now = timezone.now()

    def _advance(qs: Any, new_status: str, reason: str) -> int:
        n = 0
        for event in qs:
            old = event.status
            event.status = new_status
            event.save(update_fields=["status", "updated_at"])
            AuditLog.log(
                "event.status_changed",
                target=event,
                metadata={"from": old, "to": new_status, "reason": reason},
            )
            n += 1
        return n

    counts = {
        "public_closed": _advance(
            Event.objects.filter(
                status=EventStatus.LIVE, public_until__lt=now, permanent_archive=False
            ),
            EventStatus.PUBLIC_CLOSED,
            "public_until_passed",
        ),
        "searchable_only": _advance(
            Event.objects.filter(
                status=EventStatus.PUBLIC_CLOSED,
                searchable_until__lt=now,
                permanent_archive=False,
            ),
            EventStatus.SEARCHABLE_ONLY,
            "searchable_until_passed",
        ),
        "archived": _advance(
            Event.objects.filter(
                status=EventStatus.SEARCHABLE_ONLY,
                archive_until__lt=now,
                permanent_archive=False,
            ),
            EventStatus.ARCHIVED,
            "archive_until_passed",
        ),
    }

    # archived → pending_deletion (tras ARCHIVED_GRACE_DAYS desde archive_until)
    grace_cutoff = now - dt.timedelta(days=ARCHIVED_GRACE_DAYS)
    pending = 0
    for event in Event.objects.filter(
        status=EventStatus.ARCHIVED, archive_until__lt=grace_cutoff, permanent_archive=False
    ):
        event.status = EventStatus.PENDING_DELETION
        event.save(update_fields=["status", "updated_at"])
        AuditLog.log("event.scheduled_for_deletion", target=event)
        pending += 1
    counts["pending_deletion"] = pending

    # Disparar el borrado real de los que están en pending_deletion.
    for event in Event.objects.filter(status=EventStatus.PENDING_DELETION):
        delete_event_photos_permanently.delay(event.id)

    return counts


@shared_task(name="privacy.delete_event_photos_permanently", bind=True, max_retries=2)
def delete_event_photos_permanently(self, event_id: int) -> dict[str, int]:
    """Borra TODAS las fotos de un evento (R2 + DB). Deja el Event con
    status='deleted' para historial. Idempotente: re-correr no rompe ni duplica.
    `permanent_archive=True` lo salta (red de seguridad)."""
    event = Event.objects.get(id=event_id)
    if event.permanent_archive:
        logger.warning("delete_event %s saltado: permanent_archive=True", event_id)
        return {"skipped": 1}

    photos = Photo.objects.filter(event=event)
    keys: list[str] = []
    for photo in photos.iterator(chunk_size=500):
        keys.extend(
            k
            for k in (
                photo.original_key,
                photo.preview_key,
                photo.thumbnail_key,
                photo.branded_key,
            )
            if k
        )

    if keys:
        try:
            for batch in _chunked(keys, R2_DELETE_BATCH):
                default_storage().delete_many(batch)
        except (R2NotConfiguredError, R2UploadError):
            logger.warning("delete_event %s: R2 omitido/parcial; sigo con la DB", event_id)

    emb_deleted = FaceEmbedding.objects.filter(photo__event=event).delete()[0]
    bib_deleted = Bib.objects.filter(photo__event=event).delete()[0]
    photo_deleted = Photo.objects.filter(event=event).delete()[0]

    photo_count_at_deletion = event.photo_count
    event.status = EventStatus.DELETED
    event.photo_count = 0
    event.pending_count = 0
    event.save(update_fields=["status", "photo_count", "pending_count", "updated_at"])

    AuditLog.log(
        "event.permanently_deleted",
        target=event,
        metadata={
            "photos_deleted": photo_deleted,
            "embeddings_deleted": emb_deleted,
            "bibs_deleted": bib_deleted,
            "r2_keys_deleted": len(keys),
            "photo_count_at_deletion": photo_count_at_deletion,
        },
    )
    return {"photos_deleted": photo_deleted, "r2_keys_deleted": len(keys)}


# ---------------------------------------------------------------------------
# Cleanups varios (Fase 6)
# ---------------------------------------------------------------------------
@shared_task(name="privacy.cleanup_expired_photographer_links")
def cleanup_expired_photographer_links() -> dict[str, int]:
    """Marca inactivos los links vencidos (NO los borra: sirven para audit/stats)."""
    expired = PhotographerLink.objects.filter(is_active=True, expires_at__lt=timezone.now())
    count = expired.update(is_active=False)
    if count:
        AuditLog.log("photographer_links.auto_expired", metadata={"count": count})
    return {"expired": count}


@shared_task(name="privacy.cleanup_old_audit_logs")
def cleanup_old_audit_logs() -> dict[str, int]:
    """Borra audit logs > 2 años. ESTA es la única política que permite borrarlos."""
    cutoff = timezone.now() - dt.timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    deleted = AuditLog.objects.filter(created_at__lt=cutoff).delete()[0]
    logger.info("cleanup_old_audit_logs: borrados %d logs > 2 años", deleted)
    return {"deleted": deleted}


@shared_task(name="privacy.cleanup_failed_processing")
def cleanup_failed_processing() -> dict[str, int]:
    """Marca como failed las fotos atascadas en uploading/processing > 1 hora.

    NO borra el original de R2 (cambio post-incidente 2026-06-09): una foto
    "atascada" puede deberse a una falla TRANSITORIA de los workers — esa noche
    este cron borró los originales de 133 fotos recuperables y el fotógrafo
    tuvo que re-subirlas. Marcar como failed alcanza para sacarlas del flujo;
    los bytes quedan en R2 y un re-proceso (process_photo) las recupera. La
    limpieza física real la hace la retención del evento
    (delete_event_photos_permanently) o cleanup_orphaned_r2_objects.
    """
    cutoff = timezone.now() - dt.timedelta(hours=STUCK_PHOTO_HOURS)
    stuck = Photo.objects.filter(
        status__in=[PhotoStatus.UPLOADING, PhotoStatus.PROCESSING], updated_at__lt=cutoff
    )
    count = 0
    for photo in stuck:
        photo.status = PhotoStatus.PROCESSING_FAILED
        photo.save(update_fields=["status", "updated_at"])
        count += 1
    return {"marked_failed": count}


@shared_task(name="privacy.cleanup_orphaned_r2_objects")
def cleanup_orphaned_r2_objects() -> dict[str, int | bool]:
    """Detecta objetos en R2 sin registro en DB. Si son muchos (>100), alerta y NO
    borra (señal de bug). Si son pocos, los borra."""
    try:
        all_keys = set(default_storage().list_keys(prefix="events/"))
    except R2NotConfiguredError:
        logger.warning("cleanup_orphaned_r2: R2 no configurado")
        return {"orphaned": 0, "configured": False}

    db_keys: set[str] = set()
    for photo in Photo.objects.iterator(chunk_size=1000):
        db_keys.update(
            k
            for k in (
                photo.original_key,
                photo.preview_key,
                photo.thumbnail_key,
                photo.branded_key,
            )
            if k
        )

    orphaned = all_keys - db_keys
    if len(orphaned) > ORPHAN_ALERT_THRESHOLD:
        logger.warning(
            "cleanup_orphaned_r2: %d huérfanos (> %d). NO se borran; investigar.",
            len(orphaned),
            ORPHAN_ALERT_THRESHOLD,
        )
        return {"orphaned": len(orphaned), "deleted": False}

    if orphaned:
        default_storage().delete_many(list(orphaned))
        AuditLog.log("r2.orphans_cleaned", metadata={"count": len(orphaned)})
    return {"orphaned": len(orphaned), "deleted": True}

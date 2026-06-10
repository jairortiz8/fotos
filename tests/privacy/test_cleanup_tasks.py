"""Tests de los cleanups varios (links, stuck photos, audit logs, orphans)."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.photographers.models import PhotographerLink
from apps.photos.models import Photo, PhotoStatus
from apps.privacy.tasks import (
    cleanup_expired_photographer_links,
    cleanup_failed_processing,
    cleanup_old_audit_logs,
    cleanup_orphaned_r2_objects,
)
from tests.factories import (
    AuditLogFactory,
    EventFactory,
    PhotoFactory,
    PhotographerLinkFactory,
)


@pytest.mark.django_db
def test_expired_links_marked_inactive() -> None:
    link = PhotographerLinkFactory(is_active=True)
    PhotographerLink.objects.filter(id=link.id).update(
        expires_at=timezone.now() - dt.timedelta(days=1)
    )
    result = cleanup_expired_photographer_links()
    link.refresh_from_db()
    assert link.is_active is False
    assert result["expired"] == 1


@pytest.mark.django_db
def test_active_link_not_touched() -> None:
    link = PhotographerLinkFactory(is_active=True)  # expira en +30d (default)
    cleanup_expired_photographer_links()
    link.refresh_from_db()
    assert link.is_active is True


@pytest.mark.django_db
def test_stuck_photos_marked_failed() -> None:
    photo = PhotoFactory(event=EventFactory(), status=PhotoStatus.PROCESSING, original_key="")
    Photo.objects.filter(id=photo.id).update(updated_at=timezone.now() - dt.timedelta(hours=2))
    result = cleanup_failed_processing()
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.PROCESSING_FAILED
    assert result["marked_failed"] == 1


@pytest.mark.django_db
def test_recent_processing_photo_not_touched() -> None:
    photo = PhotoFactory(event=EventFactory(), status=PhotoStatus.PROCESSING, original_key="")
    # updated_at reciente (recién creada) → no se toca.
    cleanup_failed_processing()
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.PROCESSING


@pytest.mark.django_db
def test_old_audit_logs_deleted() -> None:
    old = AuditLogFactory()
    AuditLog.objects.filter(id=old.id).update(
        created_at=timezone.now() - dt.timedelta(days=3 * 365)
    )
    recent = AuditLogFactory()
    result = cleanup_old_audit_logs()
    assert not AuditLog.objects.filter(id=old.id).exists()
    assert AuditLog.objects.filter(id=recent.id).exists()
    assert result["deleted"] >= 1


@pytest.mark.django_db
def test_orphaned_r2_alert_when_many() -> None:
    """Si hay > 100 huérfanos, NO borra: alerta."""
    many = [f"events/x/originals/{i}.jpg" for i in range(150)]
    with patch("apps.privacy.tasks.default_storage") as factory:
        store = MagicMock()
        store.list_keys.return_value = many
        factory.return_value = store
        result = cleanup_orphaned_r2_objects()
    assert result["deleted"] is False
    assert result["orphaned"] == 150
    store.delete_many.assert_not_called()


@pytest.mark.django_db
def test_orphaned_r2_deletes_when_few() -> None:
    orphans = ["events/x/originals/ghost.jpg"]
    with patch("apps.privacy.tasks.default_storage") as factory:
        store = MagicMock()
        store.list_keys.return_value = orphans
        factory.return_value = store
        result = cleanup_orphaned_r2_objects()
    assert result["deleted"] is True
    store.delete_many.assert_called_once()
    assert AuditLog.objects.filter(action="r2.orphans_cleaned").exists()


@pytest.mark.django_db
def test_stuck_photos_keep_their_r2_original() -> None:
    """Regresión del incidente 2026-06-09: el cron marcaba failed Y BORRABA el
    original de R2 — destruyó 133 fotos recuperables que estaban atascadas por
    una falla transitoria de los workers. Marcar failed NO debe tocar R2."""
    from unittest.mock import patch

    photo = PhotoFactory(
        event=EventFactory(),
        status=PhotoStatus.PROCESSING,
        original_key="events/x/originals/keep-me.jpg",
    )
    Photo.objects.filter(id=photo.id).update(updated_at=timezone.now() - dt.timedelta(hours=2))
    with patch("apps.privacy.tasks.default_storage") as mock_storage:
        result = cleanup_failed_processing()
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.PROCESSING_FAILED
    assert result["marked_failed"] == 1
    mock_storage.assert_not_called()  # ni delete ni nada: los bytes quedan

"""Tests del cron de retención de embeddings (90 días)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.photos.models import FaceEmbedding
from apps.privacy.tasks import cleanup_old_embeddings
from tests.factories import PhotoFactory


def _emb() -> list[float]:
    return [0.01 * i for i in range(512)]


@pytest.mark.django_db
def test_cleanup_deletes_never_matched_older_than_90d() -> None:
    photo = PhotoFactory()
    fe = FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    # Forzar created_at viejo
    FaceEmbedding.objects.filter(id=fe.id).update(created_at=timezone.now() - dt.timedelta(days=91))
    result = cleanup_old_embeddings()
    assert result["deleted_count"] == 1
    assert not FaceEmbedding.objects.filter(id=fe.id).exists()


@pytest.mark.django_db
def test_cleanup_keeps_recent_embeddings() -> None:
    photo = PhotoFactory()
    fe = FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    result = cleanup_old_embeddings()
    assert result["deleted_count"] == 0
    assert FaceEmbedding.objects.filter(id=fe.id).exists()


@pytest.mark.django_db
def test_cleanup_uses_last_matched_at_when_present() -> None:
    """Embedding viejo pero matcheado recientemente → NO se borra."""
    photo = PhotoFactory()
    fe = FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    FaceEmbedding.objects.filter(id=fe.id).update(
        created_at=timezone.now() - dt.timedelta(days=200),
        last_matched_at=timezone.now() - dt.timedelta(days=5),  # match reciente
    )
    result = cleanup_old_embeddings()
    assert result["deleted_count"] == 0


@pytest.mark.django_db
def test_cleanup_deletes_old_match() -> None:
    """Embedding cuyo último match fue hace >90 días → se borra."""
    photo = PhotoFactory()
    fe = FaceEmbedding.objects.create(photo=photo, embedding=_emb())
    FaceEmbedding.objects.filter(id=fe.id).update(
        last_matched_at=timezone.now() - dt.timedelta(days=91)
    )
    result = cleanup_old_embeddings()
    assert result["deleted_count"] == 1


@pytest.mark.django_db
def test_cleanup_creates_audit_log() -> None:
    AuditLog.objects.all().delete()
    cleanup_old_embeddings()
    assert AuditLog.objects.filter(action="privacy.embeddings_cleanup").exists()

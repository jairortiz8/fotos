"""Tests del borrado permanente de eventos (delete_event_photos_permanently)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.core.models import AuditLog
from apps.events.models import EventStatus
from apps.photos.models import Bib, FaceEmbedding, Photo, PhotoStatus
from apps.privacy.tasks import delete_event_photos_permanently
from tests.factories import BibFactory, EventFactory, FaceEmbeddingFactory, PhotoFactory


def _run(event_id: int) -> dict:
    """Ejecuta la task (bind=True) síncrona."""
    return delete_event_photos_permanently.apply(args=[event_id]).get()


@pytest.fixture
def mock_storage():  # type: ignore[no-untyped-def]
    """Patchea el storage R2 para capturar delete_many sin tocar la red."""
    with patch("apps.privacy.tasks.default_storage") as factory:
        store = MagicMock()
        factory.return_value = store
        yield store


@pytest.mark.django_db
def test_delete_event_removes_photos_from_r2(mock_storage: MagicMock) -> None:
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    PhotoFactory(
        event=event,
        original_key="events/e/originals/a.jpg",
        preview_key="events/e/previews/a.webp",
        thumbnail_key="events/e/thumbnails/a.webp",
    )
    _run(event.id)
    # Se llamó delete_many con las 3 keys.
    assert mock_storage.delete_many.called
    sent = [k for call in mock_storage.delete_many.call_args_list for k in call.args[0]]
    assert "events/e/originals/a.jpg" in sent
    assert "events/e/thumbnails/a.webp" in sent


@pytest.mark.django_db
def test_delete_event_removes_embeddings_and_bibs(mock_storage: MagicMock) -> None:
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    photo = PhotoFactory(event=event, original_key="k/a.jpg")
    FaceEmbeddingFactory(photo=photo)
    BibFactory(photo=photo)
    _run(event.id)
    assert not Photo.objects.filter(event=event).exists()
    assert not FaceEmbedding.objects.filter(photo__event=event).exists()
    assert not Bib.objects.filter(photo__event=event).exists()


@pytest.mark.django_db
def test_delete_event_keeps_record_with_deleted_status(mock_storage: MagicMock) -> None:
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    PhotoFactory(event=event, original_key="k/a.jpg")
    _run(event.id)
    event.refresh_from_db()  # el Event NO se borra
    assert event.status == EventStatus.DELETED
    assert event.photo_count == 0


@pytest.mark.django_db
def test_delete_event_skipped_for_permanent_archive(mock_storage: MagicMock) -> None:
    event = EventFactory(status=EventStatus.PENDING_DELETION, permanent_archive=True)
    PhotoFactory(event=event, original_key="k/a.jpg")
    result = _run(event.id)
    assert result == {"skipped": 1}
    assert Photo.objects.filter(event=event).exists()  # NO se borró nada
    event.refresh_from_db()
    assert event.status == EventStatus.PENDING_DELETION


@pytest.mark.django_db
def test_delete_event_audited(mock_storage: MagicMock) -> None:
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    PhotoFactory(event=event, original_key="k/a.jpg")
    _run(event.id)
    assert AuditLog.objects.filter(
        action="event.permanently_deleted", target_id=str(event.id)
    ).exists()


@pytest.mark.django_db
def test_delete_event_idempotent(mock_storage: MagicMock) -> None:
    """Correr dos veces no rompe ni cambia el resultado."""
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    PhotoFactory(event=event, original_key="k/a.jpg")
    _run(event.id)
    _run(event.id)  # segunda corrida: 0 fotos, sigue deleted
    event.refresh_from_db()
    assert event.status == EventStatus.DELETED


@pytest.mark.django_db
def test_delete_event_without_r2_still_clears_db() -> None:
    """Sin R2 configurado, igual borra de la DB (R2NotConfiguredError se captura)."""
    event = EventFactory(status=EventStatus.PENDING_DELETION)
    PhotoFactory(event=event, original_key="k/a.jpg", status=PhotoStatus.APPROVED)
    _run(event.id)  # sin mock_storage → R2 no configurado en tests
    assert not Photo.objects.filter(event=event).exists()

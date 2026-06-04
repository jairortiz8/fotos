"""Tests de la retención escalonada de eventos (enforce_event_retention_policy).

CRÍTICO: estas transiciones eventualmente borran fotos reales. Probamos cada
salto con datos sintéticos y fechas forzadas.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.events.models import Event, EventStatus
from apps.privacy.tasks import enforce_event_retention_policy
from tests.factories import EventFactory


def _set_dates(event_id: int, **fields: object) -> None:
    """Setea fechas con .update() para NO disparar Event.save() (que recalcula)."""
    Event.objects.filter(id=event_id).update(**fields)


@pytest.mark.django_db
def test_transition_live_to_public_closed() -> None:
    event = EventFactory(status=EventStatus.LIVE)
    _set_dates(event.id, public_until=timezone.now() - dt.timedelta(days=1))
    enforce_event_retention_policy()
    event.refresh_from_db()
    assert event.status == EventStatus.PUBLIC_CLOSED


@pytest.mark.django_db
def test_transition_public_closed_to_searchable() -> None:
    event = EventFactory(status=EventStatus.PUBLIC_CLOSED)
    _set_dates(event.id, searchable_until=timezone.now() - dt.timedelta(days=1))
    enforce_event_retention_policy()
    event.refresh_from_db()
    assert event.status == EventStatus.SEARCHABLE_ONLY


@pytest.mark.django_db
def test_transition_searchable_to_archived() -> None:
    event = EventFactory(status=EventStatus.SEARCHABLE_ONLY)
    _set_dates(event.id, archive_until=timezone.now() - dt.timedelta(days=1))
    enforce_event_retention_policy()
    event.refresh_from_db()
    assert event.status == EventStatus.ARCHIVED


@pytest.mark.django_db
def test_transition_archived_to_pending_deletion_after_grace() -> None:
    event = EventFactory(status=EventStatus.ARCHIVED)
    # archive_until hace 31 días → pasó el grace period de 30.
    _set_dates(event.id, archive_until=timezone.now() - dt.timedelta(days=31))
    enforce_event_retention_policy()
    event.refresh_from_db()
    # pending_deletion → la task dispara el borrado (sin worker en tests, queda pending).
    assert event.status in (EventStatus.PENDING_DELETION, EventStatus.DELETED)


@pytest.mark.django_db
def test_archived_within_grace_not_deleted() -> None:
    """Dentro del grace period (< 30 días en archived), NO pasa a pending_deletion."""
    event = EventFactory(status=EventStatus.ARCHIVED)
    _set_dates(event.id, archive_until=timezone.now() - dt.timedelta(days=10))
    enforce_event_retention_policy()
    event.refresh_from_db()
    assert event.status == EventStatus.ARCHIVED


@pytest.mark.django_db
def test_permanent_archive_skipped() -> None:
    event = EventFactory(status=EventStatus.LIVE, permanent_archive=True)
    _set_dates(event.id, public_until=timezone.now() - dt.timedelta(days=400))
    enforce_event_retention_policy()
    event.refresh_from_db()
    assert event.status == EventStatus.LIVE  # no se tocó


@pytest.mark.django_db
def test_audit_log_records_transition() -> None:
    event = EventFactory(status=EventStatus.LIVE)
    _set_dates(event.id, public_until=timezone.now() - dt.timedelta(days=1))
    enforce_event_retention_policy()
    log = AuditLog.objects.filter(action="event.status_changed", target_id=str(event.id)).first()
    assert log is not None
    assert log.metadata["to"] == EventStatus.PUBLIC_CLOSED


@pytest.mark.django_db
def test_idempotent_no_double_transition() -> None:
    """Re-correr no avanza dos pasos: cada transición filtra por estado actual."""
    event = EventFactory(status=EventStatus.LIVE)
    _set_dates(event.id, public_until=timezone.now() - dt.timedelta(days=1))
    enforce_event_retention_policy()
    enforce_event_retention_policy()  # segunda corrida
    event.refresh_from_db()
    # Avanzó a public_closed (1 paso); searchable_until no venció, así que ahí queda.
    assert event.status == EventStatus.PUBLIC_CLOSED

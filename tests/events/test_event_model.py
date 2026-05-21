"""Tests del modelo Event (política de retención + slug + URLs)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.events.models import Event, EventStatus
from tests.factories import (
    ArchivedEventFactory,
    EventFactory,
    LiveEventFactory,
    PermanentArchiveEventFactory,
)


@pytest.mark.django_db
def test_event_creates_with_default_retention_dates() -> None:
    """public_until = date+90, searchable_until = date+180, archive_until = date+365."""
    event = EventFactory(date=dt.date(2026, 1, 1))
    assert event.public_until is not None
    assert event.searchable_until is not None
    assert event.archive_until is not None
    # Verificar que los gaps son los correctos
    pu, su, au = event.public_until, event.searchable_until, event.archive_until
    assert (su - pu).days == 90
    assert (au - pu).days == 275  # 365 - 90


@pytest.mark.django_db
def test_explicit_retention_dates_are_respected() -> None:
    custom_public = timezone.make_aware(dt.datetime(2030, 1, 1))
    event = EventFactory(public_until=custom_public)
    assert event.public_until == custom_public


@pytest.mark.django_db
def test_slug_auto_generated_from_name() -> None:
    event = Event.objects.create(
        name="Maratón Guatemala 2026",
        date=timezone.now().date(),
    )
    assert event.slug == "maraton-guatemala-2026"


@pytest.mark.django_db
def test_slug_uniqueness_with_collision() -> None:
    a = Event.objects.create(name="Carrera X", date=timezone.now().date())
    b = Event.objects.create(name="Carrera X", date=timezone.now().date())
    assert a.slug != b.slug
    assert b.slug == "carrera-x-2"


@pytest.mark.django_db
def test_is_public_returns_false_after_public_until() -> None:
    event = LiveEventFactory()
    # Forzar la fecha al pasado
    event.public_until = timezone.now() - dt.timedelta(hours=1)
    event.save()
    assert event.is_public() is False


@pytest.mark.django_db
def test_is_public_returns_true_when_live_and_within_window() -> None:
    event = LiveEventFactory()
    assert event.is_public() is True


@pytest.mark.django_db
def test_permanent_archive_ignores_retention_dates() -> None:
    event = PermanentArchiveEventFactory()
    # Forzamos public_until al pasado
    event.public_until = timezone.now() - dt.timedelta(days=10000)
    event.save()
    # Con permanent_archive=True, is_public() depende sólo del estado.
    assert event.is_public() is True


@pytest.mark.django_db
def test_is_searchable_after_public_close_but_within_searchable() -> None:
    event = LiveEventFactory(status=EventStatus.PUBLIC_CLOSED)
    event.public_until = timezone.now() - dt.timedelta(days=1)
    event.searchable_until = timezone.now() + dt.timedelta(days=30)
    event.save()
    assert event.is_public() is False
    assert event.is_searchable() is True


@pytest.mark.django_db
def test_is_searchable_returns_false_after_searchable_until() -> None:
    event = LiveEventFactory()
    event.searchable_until = timezone.now() - dt.timedelta(hours=1)
    event.save()
    assert event.is_searchable() is False


@pytest.mark.django_db
def test_archived_event_is_not_searchable_publicly() -> None:
    event = ArchivedEventFactory()
    assert event.is_searchable() is False
    assert event.is_archived() is True


@pytest.mark.django_db
def test_days_until_archive() -> None:
    event = LiveEventFactory()
    event.archive_until = timezone.now() + dt.timedelta(days=42, hours=1)
    event.save()
    assert event.days_until_archive() == 42


@pytest.mark.django_db
def test_days_until_archive_returns_none_for_permanent() -> None:
    event = PermanentArchiveEventFactory()
    assert event.days_until_archive() is None


@pytest.mark.django_db
def test_event_str_includes_date() -> None:
    event = EventFactory(name="Trail Antigua", date=dt.date(2026, 6, 1))
    assert "Trail Antigua" in str(event)
    assert "2026-06-01" in str(event)

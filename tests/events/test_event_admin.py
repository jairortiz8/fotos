"""Tests del EventAdmin custom (pills, días para archivar)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.events.admin import EventAdmin
from apps.events.models import Event, EventStatus
from tests.factories import LiveEventFactory, PermanentArchiveEventFactory


@pytest.fixture
def admin_instance() -> EventAdmin:
    from django.contrib import admin

    return EventAdmin(Event, admin.site)


@pytest.mark.django_db
def test_status_pill_renders_color_for_each_status(admin_instance: EventAdmin) -> None:
    """El pill debe tener color distinto según el estado y contener el display name."""
    for status in [EventStatus.DRAFT, EventStatus.LIVE, EventStatus.ARCHIVED]:
        event = LiveEventFactory(status=status)
        html = admin_instance.status_pill(event)
        assert "border-radius:999px" in html
        assert event.get_status_display() in html


@pytest.mark.django_db
def test_status_pill_falls_back_for_unknown_status(admin_instance: EventAdmin) -> None:
    event = LiveEventFactory()
    # Forzamos un valor "imposible" en el campo
    event.status = "alien-status"  # type: ignore[assignment]
    html = admin_instance.status_pill(event)
    assert "#A1A1A6" in html  # color default


@pytest.mark.django_db
def test_days_left_returns_em_dash_for_permanent(admin_instance: EventAdmin) -> None:
    event = PermanentArchiveEventFactory()
    assert admin_instance.days_left(event) == "—"


@pytest.mark.django_db
def test_days_left_returns_days_string(admin_instance: EventAdmin) -> None:
    event = LiveEventFactory()
    event.archive_until = timezone.now() + dt.timedelta(days=7, hours=2)
    event.save()
    assert admin_instance.days_left(event) == "7d"

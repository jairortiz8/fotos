"""Smoke test del comando seed_data (data de prueba para dev)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.events.models import Event
from apps.photos.models import Photo


@pytest.mark.django_db
def test_seed_data_creates_events_and_photos() -> None:
    call_command("seed_data")
    assert Event.objects.exists()
    assert Photo.objects.exists()


@pytest.mark.django_db
def test_seed_data_clean_reseeds() -> None:
    call_command("seed_data")
    first = Event.objects.count()
    call_command("seed_data", "--clean")
    assert Event.objects.count() == first  # --clean limpia y re-siembra la misma cantidad

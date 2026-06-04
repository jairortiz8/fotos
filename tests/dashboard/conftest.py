"""Fixtures compartidas de los tests del dashboard."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.events.models import EventStatus
from tests.factories import (
    AuditLogFactory,
    BibFactory,
    EventFactory,
    PendingPhotoFactory,
    PhotographerLinkFactory,
    SuperUserFactory,
    UserFactory,
)


@pytest.fixture(autouse=True)
def locmem(settings):  # type: ignore[no-untyped-def]
    """Cache en memoria para rate-limiting determinístico por test."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin(db):  # type: ignore[no-untyped-def]
    return SuperUserFactory()


@pytest.fixture
def admin_client(admin) -> Client:  # type: ignore[no-untyped-def]
    c = Client()
    c.force_login(admin)
    return c


@pytest.fixture
def non_staff(db):  # type: ignore[no-untyped-def]
    return UserFactory(is_staff=False)


@pytest.fixture
def seeded() -> dict:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    link = PhotographerLinkFactory(event=event)
    photo = PendingPhotoFactory(event=event, photographer_link=link)
    BibFactory(photo=photo)
    AuditLogFactory()
    return {"event": event, "link": link, "photo": photo}

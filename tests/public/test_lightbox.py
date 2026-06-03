"""Tests del lightbox de foto."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory, PhotoFactory


@pytest.mark.django_db
def test_lightbox_renders_approved_photo(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 200
    assert response.context["photo"] == photo


@pytest.mark.django_db
def test_lightbox_includes_bib_badges(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="1042")
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert b"1042" in response.content


@pytest.mark.django_db
def test_lightbox_increments_view_count(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, view_count=0)
    client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    photo.refresh_from_db()
    assert photo.view_count == 1


@pytest.mark.django_db
def test_lightbox_404_when_photo_not_approved(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = PhotoFactory(event=event, status=PhotoStatus.PENDING_REVIEW)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_lightbox_404_when_event_archived(client: Client) -> None:
    event = EventFactory(status=EventStatus.ARCHIVED)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_lightbox_prev_next_navigation(client: Client) -> None:
    import datetime as dt

    from django.utils import timezone

    event = EventFactory(status=EventStatus.LIVE)
    p1 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=2))
    p2 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=1))
    p3 = ApprovedPhotoFactory(event=event, capture_time=timezone.now())
    response = client.get(reverse("events:lightbox", args=[event.slug, p2.id]))
    assert response.context["prev_photo"] == p1
    assert response.context["next_photo"] == p3


@pytest.mark.django_db
def test_lightbox_htmx_returns_partial(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(
        reverse("events:lightbox", args=[event.slug, photo.id]),
        HTTP_HX_REQUEST="true",
    )
    assert b"<html" not in response.content


@pytest.mark.django_db
def test_lightbox_photographer_name_falls_back_to_admin(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, photographer_link=None, uploaded_by_admin=True)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.context["photographer_name"] == "Admin"

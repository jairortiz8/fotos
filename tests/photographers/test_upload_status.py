"""Tests del PhotographerUploadStatusView (polling de estado del portal)."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.photographers.models import PhotographerLink
from apps.photos.models import PhotoStatus
from tests.factories import EventFactory, PhotoFactory


@pytest.mark.django_db
def test_status_returns_own_photos_with_status(client: Client) -> None:
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    p1 = PhotoFactory(event=event, photographer_link=link, status=PhotoStatus.PROCESSING)
    p2 = PhotoFactory(event=event, photographer_link=link, status=PhotoStatus.PENDING_REVIEW)

    url = reverse("photographer:upload_status", args=[raw_token])
    response = client.get(url, {"ids": f"{p1.id},{p2.id}"})

    assert response.status_code == 200
    by_id = {p["id"]: p for p in json.loads(response.content)["photos"]}
    assert by_id[p1.id]["status"] == "processing"
    assert by_id[p2.id]["status"] == "pending_review"
    assert "thumb_url" in by_id[p1.id]


@pytest.mark.django_db
def test_status_excludes_other_links_photos(client: Client) -> None:
    """Un fotógrafo NO puede espiar el estado de fotos de otro link/token."""
    event = EventFactory()
    link_a, token_a = PhotographerLink.generate_token_and_create(event, name="A")
    link_b, _token_b = PhotographerLink.generate_token_and_create(event, name="B")
    mine = PhotoFactory(event=event, photographer_link=link_a)
    other = PhotoFactory(event=event, photographer_link=link_b)

    url = reverse("photographer:upload_status", args=[token_a])
    response = client.get(url, {"ids": f"{mine.id},{other.id}"})

    ids = {p["id"] for p in json.loads(response.content)["photos"]}
    assert mine.id in ids
    assert other.id not in ids


@pytest.mark.django_db
def test_status_invalid_token_returns_410(client: Client) -> None:
    url = reverse("photographer:upload_status", args=["nope-xyz"])
    response = client.get(url, {"ids": "1,2"})
    assert response.status_code == 410


@pytest.mark.django_db
def test_status_no_ids_returns_empty(client: Client) -> None:
    event = EventFactory()
    _link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    url = reverse("photographer:upload_status", args=[raw_token])
    response = client.get(url)
    assert response.status_code == 200
    assert json.loads(response.content)["photos"] == []

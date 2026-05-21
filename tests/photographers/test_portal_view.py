"""Tests del PhotographerPortalView."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.photographers.models import PhotographerLink
from tests.factories import EventFactory


@pytest.mark.django_db
def test_portal_with_valid_token_renders_200(client: Client) -> None:
    event = EventFactory()
    _link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    url = reverse("photographer:portal", args=[raw_token])
    response = client.get(url)
    assert response.status_code == 200
    assert event.name.encode() in response.content
    assert b"Portal de subida" in response.content


@pytest.mark.django_db
def test_portal_with_invalid_token_returns_410(client: Client) -> None:
    url = reverse("photographer:portal", args=["wrong-token-xyz"])
    response = client.get(url)
    assert response.status_code == 410
    assert b"Link no v" in response.content  # "Link no válido"


@pytest.mark.django_db
def test_portal_with_expired_token_returns_410(client: Client) -> None:
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    link.expires_at = timezone.now() - dt.timedelta(days=1)
    link.save()
    response = client.get(reverse("photographer:portal", args=[raw_token]))
    assert response.status_code == 410


@pytest.mark.django_db
def test_portal_with_revoked_token_returns_410(client: Client) -> None:
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    link.revoke(reason="test")
    response = client.get(reverse("photographer:portal", args=[raw_token]))
    assert response.status_code == 410


@pytest.mark.django_db
def test_portal_updates_last_used_at_and_ip(client: Client) -> None:
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    assert link.last_used_at is None

    client.get(
        reverse("photographer:portal", args=[raw_token]),
        REMOTE_ADDR="10.20.30.40",
    )
    link.refresh_from_db()
    assert link.last_used_at is not None
    # IP anonimizada: último octeto = 0
    assert link.last_used_ip == "10.20.30.0"


@pytest.mark.django_db
def test_portal_respects_x_forwarded_for(client: Client) -> None:
    """Detrás de proxy (Railway), la IP real viene en XFF."""
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="Foto")
    client.get(
        reverse("photographer:portal", args=[raw_token]),
        HTTP_X_FORWARDED_FOR="200.10.5.55, 10.0.0.1",
    )
    link.refresh_from_db()
    assert link.last_used_ip == "200.10.5.0"

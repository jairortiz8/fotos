"""Tests de la landing pública (HomeView)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus, EventVisibility
from tests.factories import EventFactory


@pytest.mark.django_db
def test_home_returns_200(client: Client) -> None:
    response = client.get(reverse("core:index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_home_lists_public_events(client: Client) -> None:
    EventFactory(name="Visible Live", status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    response = client.get(reverse("core:index"))
    assert b"Visible Live" in response.content


@pytest.mark.django_db
def test_home_hides_private_events(client: Client) -> None:
    EventFactory(name="Secreto", status=EventStatus.LIVE, visibility=EventVisibility.PRIVATE)
    response = client.get(reverse("core:index"))
    assert b"Secreto" not in response.content


@pytest.mark.django_db
def test_home_hides_archived_events(client: Client) -> None:
    EventFactory(name="Viejo", status=EventStatus.ARCHIVED, visibility=EventVisibility.PUBLIC)
    response = client.get(reverse("core:index"))
    assert b"Viejo" not in response.content


@pytest.mark.django_db
def test_home_hides_unlisted_events(client: Client) -> None:
    EventFactory(name="NoListado", status=EventStatus.LIVE, visibility=EventVisibility.UNLISTED)
    response = client.get(reverse("core:index"))
    assert b"NoListado" not in response.content


@pytest.mark.django_db
def test_home_search_bar_present(client: Client) -> None:
    EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    response = client.get(reverse("core:index"))
    assert b'name="bib"' in response.content


@pytest.mark.django_db
def test_home_counts_live_events(client: Client) -> None:
    EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    EventFactory(status=EventStatus.UPCOMING, visibility=EventVisibility.PUBLIC)
    response = client.get(reverse("core:index"))
    assert response.context["live_count"] == 1


@pytest.mark.django_db
def test_robots_txt(client: Client) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert b"Disallow: /admin/" in response.content
    assert b"Disallow: /u/" in response.content
    assert b"Sitemap:" in response.content


@pytest.mark.django_db
def test_sitemap_lists_public_events(client: Client) -> None:
    EventFactory(slug="visible-evt", status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC)
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert b"visible-evt" in response.content

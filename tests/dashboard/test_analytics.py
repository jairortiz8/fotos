"""Tests del panel de Analíticas del dashboard."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.metrics import Metric, record_event_metric
from apps.events.models import EventMetric
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory


@pytest.mark.django_db
def test_analytics_requires_staff(client: Client) -> None:
    resp = client.get(reverse("dashboard:analytics"))
    assert resp.status_code == 302
    assert "/dashboard/login/" in resp.headers["Location"]


@pytest.mark.django_db
def test_analytics_renders_for_admin(admin_client: Client) -> None:
    event = EventFactory()
    record_event_metric(event.id, Metric.DOWNLOAD, count=5)
    resp = admin_client.get(reverse("dashboard:analytics"))
    assert resp.status_code == 200
    # Total de descargas del rango aparece en la página.
    assert b"5" in resp.content


@pytest.mark.django_db
def test_analytics_invalid_days_falls_back(admin_client: Client) -> None:
    EventFactory()
    resp = admin_client.get(reverse("dashboard:analytics") + "?days=999")
    assert resp.status_code == 200
    assert resp.context["days"] == 7


@pytest.mark.django_db
def test_analytics_hourly_granularity_for_short_range(admin_client: Client) -> None:
    EventFactory()
    resp = admin_client.get(reverse("dashboard:analytics") + "?days=1")
    assert resp.status_code == 200
    assert resp.context["granularity"] == "hour"


@pytest.mark.django_db
def test_analytics_all_events_aggregates(admin_client: Client) -> None:
    e1 = EventFactory()
    e2 = EventFactory()
    record_event_metric(e1.id, Metric.VIEW, count=2)
    record_event_metric(e2.id, Metric.VIEW, count=3)
    resp = admin_client.get(reverse("dashboard:analytics") + "?event=all&days=7")
    assert resp.status_code == 200
    assert resp.context["is_all"] is True
    view_chart = next(c for c in resp.context["charts"] if c["key"] == "view")
    assert view_chart["total"] == 5


@pytest.mark.django_db
def test_analytics_filters_by_event(admin_client: Client) -> None:
    e1 = EventFactory()
    e2 = EventFactory()
    record_event_metric(e1.id, Metric.DOWNLOAD, count=10)
    record_event_metric(e2.id, Metric.DOWNLOAD, count=99)
    resp = admin_client.get(reverse("dashboard:analytics") + f"?event={e1.id}&days=7")
    assert resp.status_code == 200
    assert resp.context["selected_event"].id == e1.id
    dl_chart = next(c for c in resp.context["charts"] if c["key"] == "download")
    assert dl_chart["total"] == 10


@pytest.mark.django_db
def test_bib_search_records_a_search_metric(client: Client) -> None:
    """La búsqueda por dorsal alimenta la curva de búsquedas (sin R2)."""
    event = EventFactory()
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="1234")

    resp = client.get(reverse("events:gallery", args=[event.slug]) + "?bib=1234")
    assert resp.status_code == 200
    assert EventMetric.objects.filter(event=event, metric="search").exists()

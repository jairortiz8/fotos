"""Smoke test: todas las vistas GET del dashboard renderizan sin error (200)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

# admin_client / seeded vienen de conftest.py


@pytest.mark.django_db
def test_all_dashboard_get_views_render(admin_client: Client, seeded: dict) -> None:
    event = seeded["event"]
    photo = seeded["photo"]
    targets = [
        reverse("dashboard:dashboard_home"),
        reverse("dashboard:event_list"),
        reverse("dashboard:event_create"),
        reverse("dashboard:event_detail", kwargs={"slug": event.slug}),
        reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + "?tab=fotos",
        reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + "?tab=fotografos",
        reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + "?tab=links",
        reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + "?tab=dorsales",
        reverse("dashboard:event_update", kwargs={"slug": event.slug}),
        reverse("dashboard:generate_link", kwargs={"slug": event.slug}),
        reverse("dashboard:pending_photos"),
        reverse("dashboard:photo_detail", kwargs={"pk": photo.id}),
        reverse("dashboard:photographer_list"),
        reverse("dashboard:audit_log"),
        reverse("dashboard:stats"),
        reverse("dashboard:settings"),
    ]
    for url in targets:
        resp = admin_client.get(url)
        assert resp.status_code == 200, f"{url} devolvió {resp.status_code}"


@pytest.mark.django_db
def test_event_detail_htmx_tab_returns_partial(admin_client: Client, seeded: dict) -> None:
    event = seeded["event"]
    url = reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + "?tab=dorsales"
    resp = admin_client.get(url, headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # El partial no incluye el sidebar.
    assert b"rf-side-item" not in resp.content


@pytest.mark.django_db
def test_stats_csv_export(admin_client: Client, seeded: dict) -> None:
    resp = admin_client.get(reverse("dashboard:stats") + "?export=csv")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert b"fecha,fotos_subidas" in resp.content

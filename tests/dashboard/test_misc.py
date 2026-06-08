"""Tests de stats, audit log, fotógrafos, configuración y servicios."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditLog
from apps.dashboard import services
from apps.events.models import EventStatus
from tests.factories import (
    ApprovedPhotoFactory,
    AuditLogFactory,
    EventFactory,
    PendingPhotoFactory,
    PhotographerLinkFactory,
)


# --- Home stats ---
@pytest.mark.django_db
def test_home_shows_stats_and_pending(admin_client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    PendingPhotoFactory(event=event)
    ApprovedPhotoFactory(event=event)
    resp = admin_client.get(reverse("dashboard:dashboard_home"))
    assert resp.status_code == 200
    stats = resp.context["stats"]
    assert stats.total_events >= 1
    assert stats.total_photos >= 2
    assert resp.context["pending"].count == 1
    assert len(resp.context["uploads_by_hour"]) == 24


# --- Counters service ---
@pytest.mark.django_db
def test_recalculate_event_counters() -> None:
    event = EventFactory()
    PendingPhotoFactory(event=event)
    ApprovedPhotoFactory(event=event)
    PhotographerLinkFactory(event=event)
    services.recalculate_event_counters(event)
    event.refresh_from_db()
    assert event.photo_count == 2
    assert event.pending_count == 1
    assert event.photographer_count == 1


# --- Audit log ---
@pytest.mark.django_db
def test_audit_log_lists_and_filters(admin_client: Client) -> None:
    AuditLogFactory(action="event.created")
    AuditLogFactory(action="photo.approved")
    resp = admin_client.get(reverse("dashboard:audit_log"))
    assert resp.status_code == 200
    assert resp.context["paginator"].count == 2
    filtered = admin_client.get(reverse("dashboard:audit_log") + "?action=photo.approved")
    assert filtered.context["paginator"].count == 1


@pytest.mark.django_db
def test_audit_log_paginated(admin_client: Client) -> None:
    for _ in range(55):
        AuditLogFactory()
    resp = admin_client.get(reverse("dashboard:audit_log"))
    assert len(resp.context["entries"]) == 50  # paginate_by


@pytest.mark.django_db
def test_audit_log_has_no_delete_endpoint() -> None:
    """El audit log es de solo lectura: no existe ruta de borrado."""
    from django.urls import NoReverseMatch

    with pytest.raises(NoReverseMatch):
        reverse("dashboard:audit_delete")  # type: ignore[call-overload]


# --- Stats ---
@pytest.mark.django_db
def test_stats_view_chart_data(admin_client: Client) -> None:
    event = EventFactory()
    ApprovedPhotoFactory(event=event)
    resp = admin_client.get(reverse("dashboard:stats"))
    assert resp.status_code == 200
    assert len(resp.context["uploads_daily"]) == 30
    assert list(resp.context["top_events"])


@pytest.mark.django_db
def test_stats_export_csv(admin_client: Client) -> None:
    resp = admin_client.get(reverse("dashboard:stats") + "?export=csv")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"


# --- Photographers ---
@pytest.mark.django_db
def test_photographer_list_shows_approval_pct(admin_client: Client) -> None:
    event = EventFactory()
    link = PhotographerLinkFactory(event=event)
    link.photos_uploaded = 4
    link.save()
    for _ in range(3):
        ApprovedPhotoFactory(event=event, photographer_link=link)
    PendingPhotoFactory(event=event, photographer_link=link)
    resp = admin_client.get(reverse("dashboard:photographer_list"))
    links = list(resp.context["links"])
    assert links[0].approval_pct == 75  # 3 aprobadas / 4 subidas


@pytest.mark.django_db
def test_photographer_list_has_regenerate_button(admin_client: Client) -> None:
    """El link no se puede re-ver (hash), así que la lista ofrece 'Regenerar'."""
    link = PhotographerLinkFactory()
    resp = admin_client.get(reverse("dashboard:photographer_list"))
    assert resp.status_code == 200
    assert b"Regenerar" in resp.content
    assert reverse("dashboard:regenerate_link", kwargs={"pk": link.id}).encode() in resp.content
    assert b'id="modal-root"' in resp.content  # el modal del link nuevo tiene dónde ir


# --- Settings ---
@pytest.mark.django_db
def test_settings_change_password(admin) -> None:  # type: ignore[no-untyped-def]
    admin.set_password("old-password-1234")
    admin.save()
    client = Client()
    client.force_login(admin)
    resp = client.post(
        reverse("dashboard:settings"),
        {
            "old_password": "old-password-1234",
            "new_password1": "new-strong-password-99",
            "new_password2": "new-strong-password-99",
        },
    )
    assert resp.status_code == 302
    admin.refresh_from_db()
    assert admin.check_password("new-strong-password-99")
    assert AuditLog.objects.filter(action="admin.password_changed").exists()


@pytest.mark.django_db
def test_settings_renders(admin_client: Client) -> None:
    resp = admin_client.get(reverse("dashboard:settings"))
    assert resp.status_code == 200
    assert resp.context["retention_defaults"]["public"] == 90

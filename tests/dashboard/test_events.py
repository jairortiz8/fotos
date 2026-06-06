"""Tests de gestión de eventos y generación de links."""

from __future__ import annotations

import datetime

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditLog
from apps.events.models import Event, EventStatus, EventVisibility
from apps.photographers.models import PhotographerLink
from tests.factories import EventFactory


@pytest.mark.django_db
def test_create_event_with_defaults(admin_client: Client) -> None:
    resp = admin_client.post(
        reverse("dashboard:event_create"),
        {
            "name": "Maratón Demo 2026",
            "date": "2026-09-01",
            "visibility": EventVisibility.PUBLIC,
        },
    )
    assert resp.status_code == 302
    event = Event.objects.get(name="Maratón Demo 2026")
    # Retención estándar calculada por Event.save().
    assert event.public_until is not None
    assert event.searchable_until is not None
    assert event.archive_until is not None
    assert AuditLog.objects.filter(action="event.created", target_id=str(event.id)).exists()


@pytest.mark.django_db
def test_create_event_custom_retention(admin_client: Client) -> None:
    admin_client.post(
        reverse("dashboard:event_create"),
        {
            "name": "Permanente 2026",
            "date": "2026-09-01",
            "visibility": EventVisibility.PUBLIC,
            "permanent_archive": "on",
        },
    )
    event = Event.objects.get(name="Permanente 2026")
    assert event.permanent_archive is True


@pytest.mark.django_db
def test_event_detail_renders_all_tabs(admin_client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    for tab in ("resumen", "fotos", "fotografos", "links", "dorsales"):
        resp = admin_client.get(
            reverse("dashboard:event_detail", kwargs={"slug": event.slug}) + f"?tab={tab}"
        )
        assert resp.status_code == 200
        assert resp.context["tab"] == tab


@pytest.mark.django_db
def test_update_event_audited(admin_client: Client) -> None:
    event = EventFactory(name="Antes")
    resp = admin_client.post(
        reverse("dashboard:event_update", kwargs={"slug": event.slug}),
        {"name": "Después", "date": event.date.isoformat(), "visibility": event.visibility},
    )
    assert resp.status_code == 302
    event.refresh_from_db()
    assert event.name == "Después"
    assert AuditLog.objects.filter(action="event.updated", target_id=str(event.id)).exists()


@pytest.mark.django_db
def test_generate_link_creates_hashed_token_and_shows_raw_once(admin_client: Client) -> None:
    event = EventFactory()
    resp = admin_client.post(
        reverse("dashboard:generate_link", kwargs={"slug": event.slug}),
        {"photographer_name": "Lucía Pérez", "expires_in_days": "30"},
    )
    assert resp.status_code == 200
    link = PhotographerLink.objects.get(photographer_name="Lucía Pérez")
    # El hash en DB NO es el token plano.
    assert len(link.token_hash) == 64
    # La respuesta muestra el link con el token plano (una sola vez).
    body = resp.content.decode()
    assert "/u/" in body
    assert link.token_hash not in body  # el hash nunca se expone
    # QR embebido + audit.
    assert "data:image/png;base64," in body
    assert AuditLog.objects.filter(action="photographer_link.generated").exists()


@pytest.mark.django_db
def test_generate_link_invalid_form_rerenders(admin_client: Client) -> None:
    event = EventFactory()
    resp = admin_client.post(
        reverse("dashboard:generate_link", kwargs={"slug": event.slug}),
        {"photographer_name": "", "expires_in_days": "30"},
    )
    assert resp.status_code == 200
    assert PhotographerLink.objects.count() == 0


@pytest.mark.django_db
def test_revoke_link_marks_inactive(admin_client: Client) -> None:
    link, _ = PhotographerLink.generate_token_and_create(EventFactory(), "Test", expires_in_days=30)
    resp = admin_client.post(reverse("dashboard:revoke_link", kwargs={"pk": link.id}))
    assert resp.status_code == 302
    link.refresh_from_db()
    assert link.is_active is False


@pytest.mark.django_db
def test_regenerate_link_creates_new_and_revokes_old(admin_client: Client) -> None:
    old, _ = PhotographerLink.generate_token_and_create(EventFactory(), "Test", expires_in_days=30)
    resp = admin_client.post(reverse("dashboard:regenerate_link", kwargs={"pk": old.id}))
    assert resp.status_code == 200
    old.refresh_from_db()
    assert old.is_active is False
    assert PhotographerLink.objects.filter(is_active=True).count() == 1


@pytest.mark.django_db
def test_event_create_audit_log_records_admin(admin_client: Client, admin) -> None:  # type: ignore[no-untyped-def]
    admin_client.post(
        reverse("dashboard:event_create"),
        {"name": "Con Admin", "date": "2026-09-01", "visibility": EventVisibility.PUBLIC},
    )
    log = AuditLog.objects.get(action="event.created")
    assert log.user_id == admin.id


@pytest.mark.django_db
def test_create_event_date_in_july(admin_client: Client) -> None:
    admin_client.post(
        reverse("dashboard:event_create"),
        {"name": "Julio 5K", "date": "2026-07-15", "visibility": EventVisibility.PUBLIC},
    )
    assert Event.objects.get(name="Julio 5K").date == datetime.date(2026, 7, 15)


@pytest.mark.django_db
def test_event_form_renders_date_iso_for_html5_input() -> None:
    """Regresión: el input type=date debe traer el valor en YYYY-MM-DD.

    Con LANGUAGE_CODE=es Django lo renderizaba como d/m/Y y el `<input type=date>`,
    al no poder parsearlo, dejaba el campo VACÍO al editar — daba la sensación de
    tener que re-poner la fecha cada vez.
    """
    from apps.dashboard.forms import EventForm

    event = EventFactory(date=datetime.date(2026, 7, 19))
    assert 'value="2026-07-19"' in str(EventForm(instance=event)["date"])


@pytest.mark.django_db
def test_event_update_can_change_status_draft_to_live(admin_client: Client) -> None:
    """El form de evento ahora permite cambiar el estado (borrador → galería abierta)."""
    event = EventFactory(status=EventStatus.DRAFT)
    admin_client.post(
        reverse("dashboard:event_update", kwargs={"slug": event.slug}),
        {
            "name": event.name,
            "status": EventStatus.LIVE,
            "date": "2026-06-06",
            "visibility": EventVisibility.PUBLIC,
        },
    )
    event.refresh_from_db()
    assert event.status == EventStatus.LIVE

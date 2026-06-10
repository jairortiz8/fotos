"""Tests de la galería de evento + estados de retención."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.events.models import EventStatus, EventVisibility
from apps.photos.models import PhotoStatus
from tests.factories import (
    ApprovedPhotoFactory,
    EventFactory,
    PhotoFactory,
    PhotographerLinkFactory,
)


@pytest.mark.django_db
def test_gallery_shows_approved_photos_only(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    approved = ApprovedPhotoFactory(event=event)
    PhotoFactory(event=event, status=PhotoStatus.PENDING_REVIEW)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    # El total de fotos de la galería debe ser 1 (solo la aprobada)
    assert response.context["total_photos"] == 1
    assert approved in list(response.context["photos"])


@pytest.mark.django_db
def test_gallery_paginates_60_per_page(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    for _ in range(65):
        ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert len(response.context["photos"]) == 60
    assert response.context["total_photos"] == 65


@pytest.mark.django_db
def test_gallery_orders_by_capture_time_asc(client: Client) -> None:
    """Cronológico: la primera foto tomada (hora de disparo) aparece primero."""
    event = EventFactory(status=EventStatus.LIVE)
    older = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=2))
    newer = ApprovedPhotoFactory(event=event, capture_time=timezone.now())
    response = client.get(reverse("events:gallery", args=[event.slug]))
    photos = list(response.context["photos"])
    assert photos.index(older) < photos.index(newer)


@pytest.mark.django_db
def test_gallery_404s_when_private(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PRIVATE)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_gallery_404s_when_archived(client: Client) -> None:
    event = EventFactory(status=EventStatus.ARCHIVED)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 404
    assert b"ya no est" in response.content  # "ya no está disponible"


@pytest.mark.django_db
def test_gallery_shows_closed_message_when_public_closed(client: Client) -> None:
    event = EventFactory(status=EventStatus.PUBLIC_CLOSED)
    # public_until pasado para forzar galería cerrada
    event.public_until = timezone.now() - dt.timedelta(days=1)
    event.searchable_until = timezone.now() + dt.timedelta(days=30)
    event.save()
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    assert b"Galer" in response.content  # "Galería cerrada"


@pytest.mark.django_db
def test_gallery_searchable_only_shows_closed(client: Client) -> None:
    event = EventFactory(status=EventStatus.SEARCHABLE_ONLY)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    assert b"dorsal" in response.content.lower()


@pytest.mark.django_db
def test_gallery_upcoming_shows_coming_soon_not_closed(client: Client) -> None:
    """Un evento "Próximo" muestra "próximamente", NO el cartel de "cerrada".

    Antes un evento upcoming caía en el mismo template de "galería cerrada al
    público / ya no se muestra completa", lo que daba a entender que el evento
    había terminado cuando en realidad todavía no abrió.
    """
    event = EventFactory(status=EventStatus.UPCOMING)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    assert response.context["is_upcoming"] is True
    assert b"se publican pronto" in response.content
    assert b"ya no se muestra completa" not in response.content


@pytest.mark.django_db
def test_gallery_live_empty_shows_no_photos_message(client: Client) -> None:
    """Galería abierta sin fotos aprobadas → mensaje claro, no un grid vacío."""
    event = EventFactory(status=EventStatus.LIVE)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    assert response.context["total_photos"] == 0
    assert b"no hay fotos publicadas" in response.content


@pytest.mark.django_db
def test_gallery_404_when_slug_missing(client: Client) -> None:
    response = client.get(reverse("events:gallery", args=["no-existe"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_gallery_htmx_returns_partial(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    ApprovedPhotoFactory(event=event)
    response = client.get(
        reverse("events:gallery", args=[event.slug]),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    # El partial no tiene <html>
    assert b"<html" not in response.content


# ---------------------------------------------------------------------------
# Carpetas por fotógrafo
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_gallery_photographer_folders(client: Client) -> None:
    """?vista=fotografos lista los fotógrafos con fotos aprobadas + su conteo."""
    event = EventFactory(status=EventStatus.LIVE)
    ana = PhotographerLinkFactory(event=event, photographer_name="Ana Fotógrafa")
    ApprovedPhotoFactory(event=event, photographer_link=ana)
    ApprovedPhotoFactory(event=event, photographer_link=ana)
    # Un fotógrafo sin fotos aprobadas NO aparece como carpeta.
    PhotographerLinkFactory(event=event, photographer_name="Sin fotos")

    resp = client.get(reverse("events:gallery", args=[event.slug]) + "?vista=fotografos")
    assert resp.status_code == 200
    folders = list(resp.context["folders"])
    assert len(folders) == 1
    assert folders[0].approved_count == 2
    assert b"Ana Fot" in resp.content


@pytest.mark.django_db
def test_gallery_filter_by_photographer(client: Client) -> None:
    """?fotografo=<id> muestra sólo las fotos de ese fotógrafo."""
    event = EventFactory(status=EventStatus.LIVE)
    a = PhotographerLinkFactory(event=event)
    b = PhotographerLinkFactory(event=event)
    pa = ApprovedPhotoFactory(event=event, photographer_link=a)
    ApprovedPhotoFactory(event=event, photographer_link=b)

    resp = client.get(reverse("events:gallery", args=[event.slug]) + f"?fotografo={a.id}")
    assert resp.status_code == 200
    photos = list(resp.context["photos"])
    assert pa in photos
    assert all(p.photographer_link_id == a.id for p in photos)
    assert resp.context["photographer"].id == a.id


@pytest.mark.django_db
def test_gallery_unknown_photographer_404(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    resp = client.get(reverse("events:gallery", args=[event.slug]) + "?fotografo=999999")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_gallery_does_not_render_template_comments(client: Client) -> None:
    """Regresión del clásico de Django: un comentario {# #} MULTILÍNEA se
    renderiza como texto (pasó en prod 2026-06-09 con la tarjeta de foto).
    Siempre {% comment %}. Esto asegura que ningún resto quede visible."""
    event = EventFactory(status=EventStatus.LIVE)
    ApprovedPhotoFactory(event=event)
    resp = client.get(reverse("events:gallery", args=[event.slug]))
    assert b"{#" not in resp.content
    assert b"#}" not in resp.content
    assert b"no aparec" not in resp.content  # texto del comentario del incidente
